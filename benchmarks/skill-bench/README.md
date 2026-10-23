# skill-bench

Question it answers: **does a skill (or any instruction file) make a coding agent measurably better, and at what
cost?** Each task has an executable oracle and a known-good answer, so a result is a number and not an impression.

```bash
python3 scripts/bench/skill_bench.py validate   # prove every task can fail and can pass (run before trusting any score)
python3 scripts/bench/skill_bench.py list       # tasks per field and concept
```

## Concepts

`concepts.json` declares 27 concepts in 7 fields (ui, logic, tests, debug, security, arch, process). Each has at
least two tasks (`validate --min-per-concept 2` fails otherwise), because one task can be passed by luck and the
second is the only evidence the first was not luck. `pass_means` says in one sentence what nailing the concept is.

## A task

```
tasks/<id>/            id = <field>-<concept short>-<nn>, the directory name equals task.json "id"
  task.json            {id, field, concept, difficulty 1-3, prompt, source, message_required}
  repo/                the starting project, small, runnable with the Python standard library alone
  oracle.py            def check(repo, message) -> [{"id", "passed", "evidence"}, ...]
  ideal/solution.patch the reference answer, as a unified diff against repo/ (git apply, a/ b/ paths)
  ideal/message.md     the ideal final reply (required when message_required is true)
  alt/solution.patch   a SECOND correct answer, built differently from the ideal one
  alt/message.md       same rule as ideal/message.md
  naive/solution.patch the plausible wrong answer a default agent writes (not a strawman)
  rubric.md            optional: yes/no items a blind judge scores on the message and the diff, for what an oracle cannot see
```

- **prompt** is what the owner would type, in the owner's voice, with no hint of which skill or rule is being tested.
- **source** is `{"kind": "authored"}` or `{"kind": "public", "ref": "<url or id>", "license": "<SPDX>"}`. A task adapted
  from a public benchmark names it and its licence; the dataset itself is never copied in, only the small adaptation.
- **oracle.py** runs in `python3 -I` on a temp copy, in under a minute, with the standard library only. It imports and
  runs the code, reads files and logs in the copy, and (for process tasks) reads `message`. It must look at something:
  a check list of zero is a failure. Message checks match the fact (a path, a number, "not run"), never one phrasing.
- **alt** exists to catch an oracle fitted to one implementation: if a correct solution built differently fails the
  oracle, the oracle is wrong. Make it structurally different (another algorithm, another place for the fix).
- **naive** exists to catch an oracle that cannot tell right from wrong: it must fail at least one check. It is the
  answer a hurried agent would plausibly give (the workaround, the over-broad change, the claim without the run).
- **Start state**: the untouched repo must fail at least one check, so a task never rewards doing nothing.
- **Process tasks** (concept field `process`) are judged by what is left on disk and said: a log a Makefile target
  appends to, a file that must still exist, a script that must not have been run, the figures in the reply.

`validate` proves all of that mechanically: start fails, ideal and alt pass, naive fails, three oracle runs agree,
nothing is written to the bench. It is the gate for adding a task, not a nicety.

## Running it

```bash
B=python3\ scripts/bench/skill_bench.py
$B run --arm none --arm new=skills/gsd-musk --tasks field:process --k 3 --out ~/.cache/forge/skill-bench/runs/musk-1
$B report --out ~/.cache/forge/skill-bench/runs/musk-1 --base none
```

An arm is `none` (nothing mounted) or `NAME=DIR[:DIR]` (skill directories copied into the run's `.claude/skills/`). The agent
decides by itself whether to use the skill (that is what triggering is worth); `--force-skill` tells it to. Each run is an
isolated `claude -p` (own config dir: no user hooks, skills, CLAUDE.md or MCP, only the login) inside bubblewrap when
installed. Claude Code's own built-in skills and plugins are loaded in every arm, so they are part of the baseline. Runs are
resumable and interleaved across arms; an oracle that crashes makes an INVALID run, counted and never scored as a fail.

## Which model is which

`run` writes `<out>/run.json` first: the model alias (`--model`), the Claude Code version, `k`, the seed, the task list with a
fingerprint of the task files, and each arm's skills by sha256 (over the sorted files, each as relative path, NUL, bytes, NUL).
Every `result.json` also carries `model_id`, the exact id the CLI reported in its `init` event, because an alias such as `sonnet`
moves when the vendor ships a new model. `report` prints the model id per arm and the CLI version, and refuses (exit 1) to compare
arms that ran on different model ids unless `--allow-mixed-models`. A directory that already holds results is extended only by a run
with the same alias and the same content behind every arm name; otherwise use a new `--out` or a new arm name. `calibration.json`
records `model_ids` and `cli_version` too. A directory from before the manifest reports `(no run.json ...)`.

## Reading a score honestly

Arms are `none` (no skill), `old` and `new` (or any variants), each run the same number of times per task on the
same model. Report the pass rate per arm with a paired comparison over tasks, never a bare percentage, and report
tokens and time next to it: a skill that adds 3 points for 60% more tokens is a trade, not a win.
