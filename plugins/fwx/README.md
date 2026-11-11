# fwx

fwx is a Claude Code plugin and command line for running a software project in structured steps: a plan, waves of
agents that carry it out, and the checks that gate each wave. This folder, `plugins/fwx/` of the forge repository, is the
plugin (`fwx@fwx`, with its marketplace defined here) and the `fwx` command it ships. It was a repository of its own and
moved into forge with its history, so forge's pull requests review it; forge's README describes the workflow as a whole.

## Use

```
python3 bin/fwx help    # lists the commands
python3 bin/fwx model executor normal    # the model for a role and size
python3 bin/fwx statusline    # the status-bar line, and saves the session budget
python3 bin/fwx budget    # context and quota left
python3 bin/fwx capacity --role executor --want 3    # how many agents of a role can start now
python3 bin/fwx state resolve    # the session's phase; `state --help` lists the rest
python3 bin/fwx stage <dir> <stage>    # changes a phase's or a job's stage, if data/stages.json allows it
python3 bin/fwx rounds <dir>    # rounds a job has used of its cap; --use "<why>" spends one, --reset "<why>" restarts the count
python3 bin/fwx plan check <dir>    # the structure of a phase's plan.md (and each subphase's), premortem.md and postmortem.md; exit 1 on an error; --json
python3 bin/fwx context-base build <dir>    # the base-context file every agent of a phase starts with; `seal` marks a hand-written one, `check` fails on one over the cap, edited or stale
python3 bin/fwx discuss start --json    # what the discuss opens with: the configuration, the phases, the models and what waits in Linear; read-only
python3 bin/fwx linear list --label factory --json    # the project's Linear issues; needs LINEAR_API_KEY
python3 bin/fwx decide --facts <file>    # the merge decision for the facts of a PR: merge, handover or pending, with the rule behind each reason
python3 bin/fwx wave prepare --part-dir <dir> --plane session --branch <phase branch>    # validates a part and prints the args of `execute`; `wave check-base <sha>` is an executor's step 0 (exit 42: wrong base); `wave scratch <run> <unit>` makes the git-ignored folder in its own worktree where an agent writes its report
python3 bin/fwx verify    # runs the checks on a clean tree at HEAD and records the evidence row; exit 0 green, 1 red, 2 cannot prove the commit
python3 bin/fwx playbooks tree    # the workflow tree (an Excalidraw file): each node and its exits; --tree PATH, --scope NAME
python3 bin/fwx playbooks check    # each playbook against the tree and the block format; exit 77 without a tree; --tree PATH, --only NAME
```

Run these from this folder. The tests are not run from here: they are the `fwx` group of forge's runner, `python3 bin/forge test fwx`
from forge's top level. It prints one line per test file (`PASS`, `FAIL`, or `NOT RUN, NOT ARMED: <reason>`) and a summary. It exits 0
when nothing failed, 1 when one failed or when there is no test file. `--expect-not-run PATH[,PATH...]` declares tests that
cannot run where it is called (CI; paths as forge lists them, `plugins/fwx/tests/test_x.py`): each prints `EXPECTED NOT RUN` with its
reason and no longer makes the exit 77; with the flag an undeclared test that cannot run exits 77, a declared one that fails is still 1,
and a run where nothing passed or a declared path is no test file is 1. A command is a file, `lib/fwx/commands/<name>.py` with a `main(argv)`; its first
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

## Install

A setup tool such as forge installs and configures the plugin. By hand, add this folder as a marketplace and enable
`fwx@fwx`.

## Contributing

Work happens in forge's repository, and forge's hooks (`git config core.hooksPath githooks` at its root) run its
personal-data guard, `forge check-public`, over every commit, message and push, this folder included. The three hooks
in this folder's `githooks/` are the form for a checkout that has only this folder: they call the same guard and find
forge through `FORGE_ROOT` (the forge checkout) or, failing that, `forge` on `PATH`; with neither they refuse; forge's
own hooks are the ones in force in a forge checkout. Tests are plain scripts, run with `python3 bin/forge test fwx` from forge's top level
(`forge test` with no group runs them with the rest; CI runs this group as the `fwx` job of forge's `checks.yml`).
