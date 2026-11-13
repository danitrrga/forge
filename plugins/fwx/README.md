# fwx

fwx is a Claude Code plugin and command line for running a software project in structured steps: a plan, waves of
agents that carry it out, and the checks that gate each wave. This folder, `plugins/fwx/` of the forge repository, is the
plugin (`fwx@fwx`, with its marketplace defined here) and the `fwx` command it ships. It was a repository of its own and
moved into forge with its history, so forge's pull requests review it; forge's README describes the workflow as a whole.

## Use

```
python3 bin/fwx test    # runs every tests/test_*.py and summarises them
python3 bin/fwx help    # lists the commands
python3 bin/fwx model executor normal    # the model for a role and size
python3 bin/fwx statusline    # the status-bar line, and saves the session budget
python3 bin/fwx budget    # context and quota left
python3 bin/fwx capacity --role executor --want 3    # how many agents of a role can start now
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
python3 bin/fwx decide --facts <file>    # the merge decision for the facts of a PR: merge, handover or pending, with the rule behind each reason
python3 bin/fwx wave new --part-dir <dir> --plane session --branch <phase branch>    # validates a part and prints the args of `execute`; `wave merge`, `wave fix`, `wave revert` and `wave remove` are the steps after it, `wave` alone says whether the gate passed; `wave setup [--force]` runs the project's `worktree_setup` in the current worktree (exit 1: it failed)
python3 bin/fwx base <sha>    # an executor's step 0: exit 0 when the worktree starts at that commit, 42 when not, 43 when the project's `worktree_setup` failed in it
python3 bin/fwx scratch new <run> <unit>    # makes the folder git ignores, in its own worktree where an agent writes its report
python3 bin/fwx verify    # runs the checks on a clean tree at HEAD and records the evidence row; exit 0 green, 1 red, 2 cannot prove the commit
python3 bin/fwx playbook list    # the workflow tree (an Excalidraw file): each node and its exits; --tree PATH, --scope NAME
python3 bin/fwx walk start --dir <phase dir> --part N --round R    # UI walk: starts the seeded local app, drives browsers with guards (`walk ab`, `walk pw`), checks that every screen answers (`walk check-screens`; not for an app that declares `app_run.login`), merges findings (`walk converge`) and closes with a process count (`walk stop`, `walk stop --orphans`); NOT RUN, NOT ARMED without `app_run` or `agent_browser`
python3 bin/fwx control new --run <run dir> --screen <url>    # plants the control the walkers must find
python3 bin/fwx review new --run <run dir> --fixed <file>    # builds the review page of the fixes; `review read --run <run dir> <file>` sorts the owner's answers
python3 bin/fwx walk selftest [--json]    # proves the walk environment works, on the host or inside an image: `walk start`, the app answers 200, `agent-browser` opens it with the demo session (only an app that declares `app_run.login` has one), a non-blank capture, `walk stop` leaves 0 processes; exit 0 all pass, 1 a check failed, 2 NOT RUN, NOT ARMED
python3 bin/fwx walk capture --run <run dir> [--screens JSON] [--out DIR]    # one 1440-wide capture per walked screen, through `walk ab` and its guards, no model; one line each, exit 1 naming the missing ones
python3 bin/fwx migrate-gsd plan [--json]    # what converting a GSD .planning/ to .fwx/ would keep, purge and move; read-only. `apply` (in a worktree, own branch) does it, staged, with its checks and a rollback; `refs --base SHA [--rewrite F...] [--prefix F...]` lists and fixes the references; `leftovers [--apply]` moves the ignored files after the merge
python3 bin/fwx playbook lint    # each playbook against the tree and the block format; exit 77 without a tree; --tree PATH, --only NAME
```

Run these from this folder (`fwx test` lists the tests of the folder it is run from, not of forge's top level). `fwx test` prints one line per test file (`PASS`, `FAIL`, or `NOT RUN, NOT ARMED: <reason>`) and a summary. It exits 0
when every file passed, 1 when one failed or when there is no test file, and 77 when none failed but one could not
run (a missing tool, key or network). `--expect-not-run PATH[,PATH...]` declares tests that cannot run where it is
called (CI): each prints `EXPECTED NOT RUN: PATH: <reason>` and no longer makes the exit 77; an undeclared one still
does, a declared one that fails is still 1, and a run where nothing passed or a declared path is no test file is 1. `--jobs N` runs up to N files at once (default: the CPUs the process may use, at most 8; `--jobs 1` is one file after another); the lines and the exit code are the same at any N, and a failing file's output is shown whole. A command is a file, `lib/fwx/commands/<name>.py` with a `main(argv)`; its first
docstring line is its help, and there is no list to edit.

## Configuration

The plugin reads one file, `.claude/fwx.json` of the project's main checkout, and only through `lib/fwx/config.py`.
From a worktree or any subfolder it finds the main checkout's file through git's common directory. A setup tool
(forge) generates it and it is never edited by hand there. Without such a tool, write it by hand to the schema:

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

`walk.browser_executable` (default `null`) is the path of the browser the UI walk uses instead of the one `agent-browser`
finds, for a machine where that one goes through a wrapper (an extension, a window flag): `fwx walk ab` then adds
`--executable-path <path>` to every call. If the file is not there, `fwx walk start` is `NOT RUN, NOT ARMED` (exit 0, `armed: false`).
It is ignored inside the factory image, which has its own browser.

## Install

A setup tool such as forge installs and configures the plugin. By hand, add this folder as a marketplace and enable
`fwx@fwx`.

## Contributing

Work happens in forge's repository, and forge's hooks (`git config core.hooksPath githooks` at its root) run its
personal-data guard, `forge lint`, over every commit, message and push, this folder included. The three hooks
in this folder's `githooks/` are the form for a checkout that has only this folder: they call the same guard and find
forge through `FORGE_ROOT` (the forge checkout) or, failing that, `forge` on `PATH`; with neither they refuse; forge's
own hooks are the ones in force in a forge checkout. Tests are plain scripts, run with `python3 bin/fwx test` from this folder
(`forge test` leaves them to it and says so; CI runs them as the `fwx` job of forge's `checks.yml`).
