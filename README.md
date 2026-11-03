# fwx

fwx is a Claude Code plugin and command line for running a software project in structured steps: a plan, waves of
agents that carry it out, and the checks that gate each wave. This repository is the plugin (`fwx@fwx`, with its
marketplace defined here) and the `fwx` command it ships.

## Use

```
python3 bin/fwx test    # runs every tests/test_*.py and summarises them
python3 bin/fwx help    # lists the commands
```

`fwx test` prints one line per test file (`PASS`, `FAIL`, or `NOT RUN, NOT ARMED: <reason>`) and a summary. It exits 0
when every file passed, 1 when one failed or when there is no test file, and 77 when none failed but one could not
run (a missing tool, key or network). A command is a file, `lib/fwx/commands/<name>.py` with a `main(argv)`; its first
docstring line is its help, and there is no list to edit.

## Install

A setup tool such as forge installs and configures the plugin. By hand, add this folder as a marketplace and enable
`fwx@fwx`.

## Contributing

`git config core.hooksPath githooks` turns on the three hooks (pre-commit, commit-msg, pre-push). They call forge's
personal-data guard, `forge check-public`, and find forge through `FORGE_ROOT` (the forge checkout) or, failing that,
`forge` on `PATH`; with neither they refuse. Tests are plain scripts, run with `python3 bin/fwx test`.
