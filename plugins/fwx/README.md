# fwx

fwx is a Claude Code plugin and command line for running a software project in structured steps: a plan, waves of
agents that carry it out, and the checks that gate each wave. This folder, `plugins/fwx/` of the forge repository, is the
plugin (`fwx@fwx`, with its marketplace defined here) and the `fwx` command it ships. It was a repository of its own and
moved into forge with its history, so forge's pull requests review it; forge's README describes the workflow as a whole.

## Use

```
python3 bin/fwx help    # lists the commands
python3 bin/fwx model executor normal    # the model for a role and size
python3 bin/fwx statusline    # the status-bar line
python3 bin/fwx phase new <slug>    # the next phase folder, the session bound to it; `phase list` shows them, `phase remove <dir>` deletes one whose discuss was cancelled; `session attach <phase dir>` binds the session to one
python3 bin/fwx subphase new <phase dir> <slug>    # the next subphase folder of a phase
python3 bin/fwx milestone new [vN]    # the next milestone of a scope
python3 bin/fwx decision new --decision T --why T --support S    # a row in the phase's decisions.tsv (`--adr`: the scope's adr.tsv); `decision list` reads them, `--grep TEXT` and `--all`
python3 bin/fwx state lint <state.md>    # a state.md against its rules; exit 1 on an error
python3 bin/fwx report lint <report.md>    # a phase report against its rules, the same way
python3 bin/fwx session    # the session's phase; `fwx --help` lists every command, grouped by object
python3 bin/fwx stage <dir> <stage>    # changes a phase's or a job's stage, if data/stages.json allows it
python3 bin/fwx rounds <dir>    # rounds a job has used of its cap; --use "<why>" spends one, --reset "<why>" restarts the count
python3 bin/fwx plan lint <dir>    # the structure of a phase's plan.md (and each subphase's), premortem.md and postmortem.md; exit 1 on an error; --json
python3 bin/fwx context new <dir>    # the base-context file every agent of a phase starts with; `context seal` marks a hand-written one, `context lint` fails on one over the cap, edited or stale
python3 bin/fwx discuss --json    # what the discuss opens with: the configuration, the phases, the models and what waits in Linear; read-only
python3 bin/fwx linear list --label factory --json    # the project's Linear issues; needs LINEAR_API_KEY
python3 bin/fwx project state --json    # open PRs, the default branch's CI and open Linear issues; a section without `gh` login or LINEAR_API_KEY is `{"not_run": ...}`, exit 77
python3 bin/fwx decide --facts <file>    # the merge decision for the facts of a PR: merge, handover or pending, with the rule behind each reason
python3 bin/fwx wave run --part-dir <dir> --plane session --branch <phase branch>    # runs a whole part: validates it and checks its base, then every wave, the gate and the review, each agent an Orca worker; prints `run <R> <done|failed|needs-owner>: <why>` and exits 0, 1 or 3 (before any worker: 1 a red base, 77 a base check out of time, 2 a refusal); `--fix F`, `--revert IDS`, `--from gate` and `--resume R` take a correction, a revert, the gate again and a cut run up; `--orchestrator orca_session_id:<uuid>` (the chat that starts the run; session plane only) sends that chat each worker's question and one status line per wave and at the end, and `orca orchestration send --to dispatch:<D>` answers the worker; `wave list` shows the runs
python3 bin/fwx wave new --part-dir <dir> --plane session --branch <phase branch>    # only the validation and the base checks of `wave run`, printing the part's args; `wave merge`, `wave fix`, `wave revert`, `wave remove`, `wave report`, `wave review` and `wave findings` are the steps `wave run` makes, each recorded in the run's files, `wave` alone says whether the gate passed; `wave setup [--force]` runs the project's `worktree_setup` in the current worktree (exit 1: it failed)
python3 bin/fwx base <sha>    # an executor's step 0: exit 0 when the worktree starts at that commit, 42 when not, 43 when the project's `worktree_setup` failed in it
python3 bin/fwx scratch new <run> <unit>    # makes the folder git ignores, in its own worktree where an agent writes its report
python3 bin/fwx verify    # runs the checks on a clean tree at HEAD and records the evidence row; exit 0 green, 1 red, 2 cannot prove the commit
python3 bin/fwx walk start --dir <phase dir> --part N --round R    # UI walk: starts the seeded local app, drives browsers with guards (`walk ab`, `walk pw`), checks that every screen answers (`walk check-screens`; not for an app that declares `app_run.login`), merges findings (`walk converge`) and closes with a process count (`walk stop`, `walk stop --orphans`); NOT RUN, NOT ARMED without `app_run` or `agent_browser`
python3 bin/fwx control new --run <run dir> --screen <url>    # plants the control the walkers must find: a link that leads to a page that does not exist (`--kind hierarchy`: a title shrunk to body size, for the critic); `control judge --run <run dir> <findings files>` says, by code, whether a finding names it
python3 bin/fwx review new --run <run dir> --fixed <file>    # builds the review page of the fixes; `review read --run <run dir> <file>` sorts the owner's answers
python3 bin/fwx walk selftest [--json]    # proves the walk environment works, on the host or inside an image: `walk start`, the app answers 200, `agent-browser` opens it with the demo session (only an app that declares `app_run.login` has one), a non-blank capture, `walk stop` leaves 0 processes; exit 0 all pass, 1 a check failed, 2 NOT RUN, NOT ARMED
python3 bin/fwx walk capture --run <run dir> [--screens JSON] [--out DIR]    # one 1440-wide capture per walked screen, through `walk ab` and its guards, no model; one line each, exit 1 naming the missing ones
python3 bin/fwx migrate-gsd plan [--json]    # what converting a GSD .planning/ to .fwx/ would keep, purge and move; read-only. `apply` (in a worktree, own branch) does it, staged, with its checks and a rollback; `refs --base SHA [--rewrite F...] [--prefix F...]` lists and fixes the references; `leftovers [--apply]` moves the ignored files after the merge
```

Run these from this folder. The suite is not one of them: forge runs it, as the `fwx` group of its test runner, from forge's top
level (`python3 bin/forge test fwx`); the plugin has no test command of its own, and asking for the old one is refused with a line that names that command. The group prints one line per test file
(`PASS`, `FAIL`, or `NOT RUN, NOT ARMED: <reason>`) and a summary, and runs each file with this folder as working directory. It exits 0
when every file passed, 1 when one failed or when there is no test file, and 77 when none failed but one could not run (a missing tool,
key or network); without this folder (a checkout without the plugin) it prints one SKIP line and exits 0. `--expect-not-run PATH[,PATH...]`
declares tests that cannot run where it is called (CI; paths relative to this folder, as the group prints them): each prints
`EXPECTED NOT RUN: PATH: <reason>` and no longer makes the exit 77; an undeclared one still does, a declared one that fails is still 1,
and a run where nothing passed or a declared path is no test file is 1. `--jobs N` runs up to N files at once (default: the CPUs the
process may use, at most 8; `--jobs 1` is one file after another); the lines and the exit code are the same at any N, and a failing
file's output is shown whole. `python3 bin/forge test` with no group runs forge's own tests and leaves this suite out. A command is a file, `lib/fwx/commands/<name>.py` with a `main(argv)`; its first
docstring line is its help, and there is no list to edit.

## Orca plugin

`orca/` is an Orca plugin (Orca 1.4.259 or later): a status bar chip (`<project> · <profile> · ▰▰▰▱▱▱▱▱`, the bar being `progress` of `fwx session --json`; hover shows the roadmap, click opens the "Session" panel) for the fwx session of the workspace in view.
Load it with `orca plugin dev load plugins/fwx/orca` (Orca prints a fingerprint and the access it asks for: read the workspaces, run `fwx` in them; approve with `--approve <fingerprint>`), remove it with `orca plugin dev unload plugins/fwx/orca`.
Its tests are `orca plugin test plugins/fwx/orca` and `orca plugin check plugins/fwx/orca`; `fwx` must be on Orca's own PATH,; loaded from a folder its key is `local.fwx-session` (the worker opens its own panel by that key).

## Configuration

The plugin reads one file, `.claude/fwx.json` of the project's main checkout, and only through `lib/fwx/config.py`.
From a worktree or any subfolder it finds the main checkout's file through git's common directory. A setup tool
(forge) generates it: `forge sync --apply` rewrites it from the project's file (`config/projects/<name>.json`) and from the
`framework` section of forge's `config/forge.json`, so a hand edit there is lost on the next sync. Without such a tool, write it by hand to the schema:

```json
{ "schema": 1,
  "models": { "executor": { "small": "haiku", "normal": "sonnet", "big": "sonnet" } },
  "rounds": 3,
  "linear": { "labels": { "needs-owner": "your-label-for-it" } } }
```

Keys you leave out keep the defaults in `DEFAULTS` (`config.py`), so a file may hold only what you change; a `models`
entry may name one role and one size. `schema` must be 1. A model is an alias (`sonnet`, `opus`, `haiku`, `fable`),
never a full model id, and the roles and sizes are the `ROLES` and `SIZES` of `config.py`. A bad file is an error that names the
fix. With no file, the defaults apply and one line on stderr says so.

`fwx model <role> <size>` prints the model for a role and size and exits 2 on an unknown role or size, naming the valid
ones. `linear.labels` maps a label's neutral name in this repository to the name it has in your Linear workspace; a
name with no entry is used as it is.

`limits` is the most agents at once, a fixed number that nothing measures: `default_cap` is `{"supervised": 3, "unattended": 4}` (the
owner present, nobody present) and `per_project` maps a role to its own number (`executor`, `ui-walker`). `fwx wave run` (and `wave new`) read the
executor's as `cap` of the part's `args`, `fwx walk start` the walkers' as `capacity.cap`, and the built base context states them to every agent that gets a base (the `map` and `map+decided` kinds of `data/context-base.tsv`; the `none` kinds get none), but not one written by hand and sealed with `fwx context seal`, which is not built. A value that is not a positive whole number is an error that names the key, never "no limit". The agents of other sessions
are not counted, and the older keys `on`, `ram_min_free_gb` and `ram_per_agent_mb` are ignored.

`project.check_timeout_s` (default `1200`) is the seconds one check of `project.checks` or `checks_quick` may run before fwx stops it: `fwx verify`, the
gate, `fwx wave new`'s base checks and `fwx wave merge` use it, and a base check stopped by it is `NOT RUN` and names the limit it had. A project whose suite
needs longer sets it (forge's project field of the same name); anything but a positive whole number is an error that names the key.

`walk.browser_executable` (default `null`) is the path of the browser the UI walk uses instead of the one `agent-browser`
finds, for a machine where that one goes through a wrapper (an extension, a window flag): `fwx walk ab` then adds
`--executable-path <path>` to every call. If the file is not there, `fwx walk start` is `NOT RUN, NOT ARMED` (exit 0, `armed: false`).
It is ignored inside the factory image, which has its own browser.

### The keys

Every key of `DEFAULTS` (`config.py`), with what it changes and its default; a key left out of the file keeps the default.

- `schema`: the file's format; must be `1`.
- `framework` (default `true`): whether the project runs on the framework; `fwx discuss` stops when it is `false`.
- `project`: the project's own facts, one line each below.
- `models`: the model alias for each role and size, seeded by `_seed()` in `config.py` (the planner on `opus`, the detector on `haiku`, the rest `sonnet` with the exceptions that function lists); `fwx model <role> <size>` prints one.
- `limits`: the most agents at once, above.
- `rounds` (default `3`): the cap of rounds a job may use; `fwx rounds <dir>` counts against it.
- `critique_rounds_unattended` (default `2`): the cap of critique rounds of a plan when nobody is present.
- `linear`: `linear.labels` maps neutral label names to the names in your Linear workspace (default none).
- `walk`: the UI walk's keys, above.
- `factory`: the factory's switches. `mode` (default `"off"`) is the project's factory mode; `ui_bugs` (`false`) sends mechanical UI fixes to it, and `fwx discuss` reads it. `watchdog_nudge_min` (`30`), `watchdog_fail_min` (`30`), `cost_warn_x_median` (`3`), `tick_trigger` (`null`) and `classifier` (`"suggest"`) are kept for the factory's loop; no command of this plugin reads them yet.
- `weekly`: the weekly improvement cycle's switches: `on` (`true`), `min_sessions` (`5`), `trigger` (`null`), `precision_low` (`0.7`), `precision_min_marks` (`20`), `cost_target` (`0.05`), `improve` (`{}`) and `projects` (`[]`). No command of this plugin reads them yet.
- `integrations`: which optional tools are armed, each `false` by default: `consent` (the consent window), `notifications` and `agent_browser` (`fwx walk start` is `NOT RUN, NOT ARMED` without it). forge writes them from its own switches and has none for `notifications`, so that one stays `false`.
- `paths` (default `{}`): where a project's own tools are; `paths.verdict` is the verdict tool `fwx discuss` reports to the demo agent.

The `project` table:

- `project.name`, `project.main_checkout`: the project's name and main checkout; forge writes them, and without a file they are the folder's name and path.
- `project.linear_project`: the Linear project the framework files issues in (default none; forge uses the project file's `linear_project`, else the remote's name).
- `project.default_branch`: the branch pull requests go to, which `fwx verify` treats as the default branch (forge reads it from git); `project.factory_branch` (default `"factory"`) is where factory work lands.
- `project.checks` (default `[]`): the commands that gate a wave; `project.checks_quick` (`[]`) are the quick ones `fwx wave` runs in each worktree. At the end of a part the gate is GitHub CI when it can answer (the branch is pushed and a draft pull request opened, and the CI run on it stands for `project.checks`); with no GitHub origin, no CI file or no answer, `project.checks` run here. A check CI cannot run goes in `checks_quick`, which always runs here.
- `project.protected_paths` (`[]`): globs a task may not write without the security review, added to the decide table's own.
- `project.production` (`{"branches": [], "commands": []}`): the branches a merge ships to users from and the commands that deploy; a deploy runs only through the consent window.
- `project.verdict_command` (default none): the command the demo agent runs to show a UI change in the app.
- `project.ui` (`false`): whether the project has a screen, so the UI walk applies.
- `project.app_run` (default none): how the UI walk starts the app.
- `project.worktree_setup` (`[]`): the shell commands `fwx wave setup` runs in each new worktree, before any check.
- `project.check_timeout_s` (`1200`): above.

### Changing a key

The file is generated, so change its source and not the file. To change one, ask an agent: say which key and which value, and it edits the setup tool's source (for forge, `config/projects/<name>.json` for a `project` key, `config/forge.json`'s `framework` section for any other), then runs `forge sync --apply` (plain `forge sync` only shows what would change). Not every key reads from there, and editing the source forge ignores changes nothing: `factory.mode` is the project file's `factory` and `factory.ui_bugs` its `factory_ui_bugs` (the `framework` section's `factory` table fills only the other `factory` keys); `project.name` is the project file's `project`; `project.default_branch` is read from git, so it changes with the repository's branch and not with a file; `project.factory_branch` is fixed at `"factory"`; and each `integrations` switch is forge's own switch for that tool in `config/forge.json`, not a key of the `framework` section. Where no setup tool writes the file, it edits `.claude/fwx.json` by hand to the schema above. Either way, for a model it ends by running `fwx model <role> <size>` to show the new value is the one in force; no command reads the other keys back, so for those it re-reads the file.

### What is not configurable

The fixed core is code and text, changed by a change to this plugin and never by a key: the stage table (`data/stages.json`), the plan's format, the blocks that stay in every plan and report, the merge rules of `fwx decide`, and the texts of the agents and skills.

### Platform

fwx runs on Linux only: its cleanup, `worktree_setup` and UI walk read `/proc`. No key changes that.

## Install

A setup tool such as forge installs and configures the plugin. By hand, add this folder as a marketplace and enable
`fwx@fwx`.

## Contributing

Work happens in forge's repository, and forge's hooks (`git config core.hooksPath githooks` at its root) run its
personal-data guard, `forge lint`, over every commit, message and push, this folder included. The three hooks
in this folder's `githooks/` are the form for a checkout that has only this folder: they call the same guard and find
forge through `FORGE_ROOT` (the forge checkout) or, failing that, `forge` on `PATH`; with neither they refuse; forge's
own hooks are the ones in force in a forge checkout. Tests are plain scripts, run with `python3 bin/forge test fwx` from forge's top level
(`forge test` with no group leaves them out and says so; CI runs the group as the `fwx` job of forge's `checks.yml`).
