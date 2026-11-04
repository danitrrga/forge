---
{
  "size": {
    "tag": "small",
    "parts": 1,
    "agents": 3
  },
  "criteria": [
    {
      "id": "C1",
      "text": "`calc.py` evaluates an expression with the four operations, brackets and a leading minus, and prints `0.1 + 0.2` as 0.3.",
      "measure": "`python3 tests/test_core.py` and `python3 tests/test_cli.py` exit 0."
    },
    {
      "id": "C2",
      "text": "A division by zero prints a message and stops with exit code 1.",
      "measure": "`python3 calc.py \"1 / 0\"; echo $?` prints the message and then 1."
    },
    {
      "id": "C3",
      "text": "An operator dropped into `plugins/` is available without editing the core.",
      "measure": "`python3 tests/test_plugins.py` and `python3 tests/test_percent_plugin.py` exit 0."
    },
    {
      "id": "C4",
      "text": "`calc history` lists what was calculated and replays an entry.",
      "measure": "`python3 tests/test_cli_history.py` exits 0."
    }
  ],
  "tasks": [
    {
      "id": "T1",
      "part": 1,
      "type": "feature",
      "wave": 1,
      "files": [
        "calc.py",
        "tests/test_core.py"
      ],
      "depends_on": [],
      "tests": [
        {
          "run": "python3 tests/test_core.py",
          "measures": "precedence, brackets and a leading minus of `evaluate()`",
          "red": "against an `evaluate()` that ignores precedence: FAIL: 2 + 3 * 4: got 20, want 14"
        }
      ],
      "size": "normal",
      "ui": false
    },
    {
      "id": "T2",
      "part": 1,
      "type": "feature",
      "wave": 2,
      "files": [
        "calc_plugins.py",
        "tests/test_plugins.py"
      ],
      "depends_on": [
        "T1"
      ],
      "tests": [
        {
          "run": "python3 tests/test_plugins.py",
          "measures": "a plugin file dropped in `plugins/` registers its operator",
          "red": "against a registry that never scans the folder: FAIL: plugin operator %: not registered"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T3",
      "part": 1,
      "type": "feature",
      "wave": 2,
      "files": [
        "calc_config.py",
        "tests/test_config.py"
      ],
      "depends_on": [
        "T1"
      ],
      "tests": [
        {
          "run": "python3 tests/test_config.py",
          "measures": "the settings file is read and a bad value is reported",
          "red": "against a loader that ignores the file: FAIL: precision 4: got 10, want 4"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T4",
      "part": 1,
      "type": "feature",
      "wave": 2,
      "files": [
        "calc_history.py",
        "tests/test_history.py"
      ],
      "depends_on": [
        "T1"
      ],
      "tests": [
        {
          "run": "python3 tests/test_history.py",
          "measures": "each evaluated expression is appended to the history file",
          "red": "against a store that never writes: FAIL: history after two runs: got [], want 2 lines"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T5",
      "part": 1,
      "type": "feature",
      "wave": 3,
      "files": [
        "calc.py",
        "tests/test_cli.py"
      ],
      "depends_on": [
        "T1",
        "T3"
      ],
      "tests": [
        {
          "run": "python3 tests/test_cli.py",
          "measures": "the argument form, the line-by-line form and the exit code of a division by zero",
          "red": "against a `main()` that lets the ZeroDivisionError out: FAIL: 1 / 0: exit 1 expected, got a traceback"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T6",
      "part": 1,
      "type": "feature",
      "wave": 3,
      "files": [
        "plugins/percent.py",
        "tests/test_percent_plugin.py"
      ],
      "depends_on": [
        "T2"
      ],
      "tests": [
        {
          "run": "python3 tests/test_percent_plugin.py",
          "measures": "the example `%` operator loads through the registry",
          "red": "against a plugin with no `register()`: FAIL: percent plugin: not loaded"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T7",
      "part": 1,
      "type": "feature",
      "wave": 3,
      "files": [
        "calc_replay.py",
        "tests/test_replay.py"
      ],
      "depends_on": [
        "T4"
      ],
      "tests": [
        {
          "run": "python3 tests/test_replay.py",
          "measures": "`replay(n)` evaluates the n-th past expression again",
          "red": "against a `replay()` that returns the text: FAIL: replay 1: got '2 + 3', want 5"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T8",
      "part": 1,
      "type": "feature",
      "wave": 4,
      "files": [
        "calc.py",
        "tests/test_cli_history.py"
      ],
      "depends_on": [
        "T5",
        "T7"
      ],
      "tests": [
        {
          "run": "python3 tests/test_cli_history.py",
          "measures": "`calc history` lists the past expressions and `calc history 2` replays one",
          "red": "against a CLI without the subcommand: FAIL: calc history: exit 2"
        }
      ],
      "size": "small",
      "ui": false
    },
    {
      "id": "T9",
      "part": 1,
      "type": "feature",
      "wave": 4,
      "files": [
        "README.md"
      ],
      "depends_on": [
        "T5"
      ],
      "tests": [
        {
          "run": "python3 -c \"import re,sys; sys.exit(0 if re.search('python3 calc.py', open('README.md').read()) else 1)\"",
          "measures": "the README shows how to run the calculator",
          "red": "against a README without the command: exit 1"
        }
      ],
      "size": "small",
      "ui": false
    }
  ],
  "not_built": [
    {
      "what": "powers and functions",
      "why": "no use for them yet."
    }
  ],
  "later": []
}
---

## Goal
A terminal calculator that evaluates expressions, with a plugin system for new operators, a settings file and a history of what was calculated.

## Approach
T1 is the evaluator (D1, D3). T5 is the command line: an expression as the argument or one per line (D2), division by zero reported with exit code 1 (D3). The results are exact decimals (D4), through the same parser in T1. T2 and T6 make operators loadable from a folder, T3 reads the settings, T4, T7 and T8 keep a history and replay it, and T9 writes the README. Waves: T1 first; the plugin loader, the settings and the history store in one wave, as they share no file; then the command line, the example plugin and the replay; the history subcommand and the README last.

## Size
Small at the pre-mortem, nine tasks in the plan. The calculator was asked for as one small file; this plan keeps `calc.py` and adds four more modules because three things are built in as well. A plugin system, so that the next operator is a file in `plugins/` and not an edit to the evaluator. A settings file, `calc.toml`, for the number of places and the output format, so that nobody edits constants. A history file with a `calc history` command, so that a calculation can be replayed after the session ends. They make the work larger than a small plan allows, but each is a module of its own, built in one wave, so the plan is no slower than a small one would be.
