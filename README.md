# fwx

fwx is a Claude Code plugin and command line for running a software project in structured steps: a plan, waves of
agents that carry it out, and the checks that gate each wave. This repository is the plugin (`fwx@fwx`, with its
marketplace defined here) and the `fwx` command it ships.

## Use

```
python3 bin/fwx test    # runs every tests/test_*.py and summarises them
python3 bin/fwx help    # lists the commands
python3 bin/fwx model executor normal    # the model for a role and size
python3 bin/fwx statusline    # the status-bar line, and saves the session budget
python3 bin/fwx budget    # context and quota left
python3 bin/fwx state resolve    # the session's phase; `state --help` lists the rest
python3 bin/fwx stage <dir> <stage>    # changes a phase's or a job's stage, if data/stages.json allows it
python3 bin/fwx rounds <dir>    # rounds a job has used of its cap; --use "<why>" spends one, --reset "<why>" restarts the count
python3 bin/fwx context-base build <dir>    # the base-context file every agent of a phase starts with; `seal` marks a hand-written one, `check` fails on one over the cap, edited or stale
python3 bin/fwx linear list --label factory --json    # the project's Linear issues; needs LINEAR_API_KEY
python3 bin/fwx decide --facts <file>    # the merge decision for the facts of a PR: merge, handover or pending, with the rule behind each reason
python3 bin/fwx verify    # runs the checks on a clean tree at HEAD and records the evidence row; exit 0 green, 1 red, 2 cannot prove the commit
python3 bin/fwx playbooks tree    # the workflow tree (an Excalidraw file): each node and its exits; --tree PATH, --scope NAME
python3 bin/fwx playbooks check    # each playbook against the tree and the block format; exit 77 without a tree; --tree PATH, --only NAME
```

`fwx test` prints one line per test file (`PASS`, `FAIL`, or `NOT RUN, NOT ARMED: <reason>`) and a summary. It exits 0
when every file passed, 1 when one failed or when there is no test file, and 77 when none failed but one could not
run (a missing tool, key or network). `--expect-not-run PATH[,PATH...]` declares tests that cannot run where it is
called (CI): each prints `EXPECTED NOT RUN: PATH: <reason>` and no longer makes the exit 77; an undeclared one still
does, a declared one that fails is still 1, and a run where nothing passed or a declared path is no test file is 1. A command is a file, `lib/fwx/commands/<name>.py` with a `main(argv)`; its first
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

`git config core.hooksPath githooks` turns on the three hooks (pre-commit, commit-msg, pre-push). They call forge's
personal-data guard, `forge check-public`, and find forge through `FORGE_ROOT` (the forge checkout) or, failing that,
`forge` on `PATH`; with neither they refuse. Tests are plain scripts, run with `python3 bin/fwx test`.
