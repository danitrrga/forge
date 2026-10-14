# forge

forge keeps the Claude Code (and, optionally, Codex) configuration of every project on your machine in one
checkout, and generates each project's files from it: MCP servers, which skills and plugins a project loads,
hooks, permissions and a shared instruction document. You edit one place, run one command, and every project
agrees.

What it writes is generated and overwritten on every run: the per-project keys in `~/.claude.json`, each
project's `.claude/settings.local.json`, the hook rows in `~/.claude/settings.json` and, with Codex on, its
`config.toml` and `hooks.json`. Everything is a **dry-run until you pass `--apply`**, secrets live in one
git-ignored file and are referred to as `${VAR}`, and a project can be marked so that forge never writes a file
git tracks in it.

## Requirements

Linux, Python 3.10 or newer, git and Claude Code. pnpm (only for GSD) and Codex are optional. forge
checks each one and tells you which are missing.

## Install

```
git clone https://github.com/danitrrga/forge ~/forge && cd ~/forge && python3 bin/forge init
python3 bin/forge add ~/code/myproject
```

`forge init` (`--yes` takes every detected default, `--with a,b` and `--without a,b` switch integrations,
`--track` versions your data, see below):

1. checks python, git, `claude`, `pnpm` and `codex`, one line each;
2. asks at most two questions, and only for tools it found: manage Codex's config too, and install GSD;
3. writes your data into the checkout: `config/forge.json` (your switches), a profile for the checkout itself,
   an empty MCP registry, `credentials/secrets.json` (mode 600), `docs/AGENT-SYSTEM.md` (from
   `examples/AGENT-SYSTEM.md`) and an empty `skills/`;
4. with GSD on, runs GSD's own installer, `pnpm dlx get-shit-done-cc@latest --claude --global`;
5. runs `forge sync --apply --all`, which installs a SessionStart hook in `~/.claude/settings.json`, and then
   `forge doctor`; it exits with doctor's status.

Outside the checkout `init` touches `~/.claude/settings.json` (merged, never replaced), `~/.claude.json`, the
`~/.claude/skills` links, and with Codex on `~/.codex/`. Your own `CLAUDE.md`, `AGENTS.md` and `.gitignore` in a
project are never written by `forge add`.

`forge add PATH [--name NAME] [--writes-tracked-files]` registers a project: it writes
`config/profiles/NAME.claude.json` and runs `forge sync --apply --project NAME`. It refuses a path that is not a
directory, a name that is already registered and a name that is not kebab-case. By default forge writes no
file that git tracks in the project (no pointer in its `CLAUDE.md`, no `.gitignore` line); the flag allows it.

## Where your own skills go

forge ships **no skills**. Put yours in `skills/<name>/SKILL.md` inside the checkout, then run
`forge sync --apply`: forge links each one into `~/.claude/skills`, and a project's profile decides which of
them it loads (`skills_keep`, `["*"]` for all). The engine's git ignores `skills/`, so `git pull` never
conflicts with them; `forge init --track` creates a second, local history for your data when you want it
versioned.

Third-party skills come from their own repositories, for example Anthropic's `skill-creator`,
`kepano/obsidian-skills`, `pbakaus/impeccable` and `Panniantong/Agent-Reach`. The `gsd-*` skills are GSD's own, unpatched,
installed from its package by `forge init` with pnpm when the `gsd` integration is on; forge does not touch them
afterwards (`gsd_patches` in `config/forge.json` is false, which is what `forge init` writes).

## Profiles

One file per project, `config/profiles/<name>.claude.json`: its path, the MCP servers it gets from
`config/mcp-registry.json`, the skills and plugins it keeps, permissions, env and hooks. The accepted fields and
their types are `PROFILE_FIELDS` in `forge/lib.py`, and `forge sync` names a field of the wrong type instead of
guessing. A server's secrets are written `${VAR}` in the registry and resolved from `credentials/secrets.json`;
a server whose secret is missing is not written.

## Optional integrations

All are off for a new user. Each is a switch under `integrations` in `config/forge.json`; set it to
`true` and run `forge sync --apply --all`. Switching one off removes only the entries forge itself wrote, never
a hook you installed another way.

| Integration | Turns on | Needs |
|---|---|---|
| `codex` | `~/.codex/hooks.json` and `~/.codex/skills`, each project's `.codex/config.toml` and `.agents/skills` links | `codex` on PATH |
| `gsd` | the `gsd-*` skills, agents and engine from `get-shit-done-cc`, installed unpatched by `forge init`, and its three hooks | `pnpm` |
| `caveman` | two hooks around the `caveman` plugin: one injects your own rules from `hooks/caveman_house_rules.md` if you write that file, one makes a `/caveman` level stick in the profile | the plugin, installed in Claude Code |
| `hindsight` | the Hindsight coding-agent hooks and its rendered config | Hindsight's coding-agents package and `config/hindsight-coding-agents.json`; written for one machine's layout, so read `forge/memory.py` first |

A fifth switch, `jev`, belongs to code that is not part of this repository and is not documented here.

`forge/hooks.py` also writes a few rows that are safe on any machine and need no switch: the SessionStart sync,
the memory check, a notifier that exits quietly without `omarchy-notification-send`, and a router that reads
`infra/ref/ref-index.tsv` when a project has one. Your own rows go in `user_hooks` in `config/forge.json`.

## Commands

```
forge sync [--apply] [--project NAME | --all]   what would change (or change) in every generated file
forge doctor [NAME]                             one PASS / FAIL / SKIP / WARN line per check; exit 1 on a FAIL
forge test                                      every tracked test_*.py, at nice 19
forge toolchain [--fix]                         the global npm and pip packages config/toolchain.json pins
forge commit -m MESSAGE [PATH...]               commit each changed path to the history that owns it
forge check-public --all                        personal data in the files the engine publishes
forge metrics NAME [--baseline]                 a project's harness cost, from its Claude Code transcripts
```

`forge doctor` reports what it looked at. A check with nothing to look at (no skills, an integration that is off,
no toolchain file) prints `SKIP ... NOT RUN, NOT ARMED` and is neither a pass nor a failure; a check that is on
and broken is a FAIL that names the fix. Run `forge doctor NAME` to see only the rows that concern one project.

`forge commit` stages each changed path in the history that owns it. A path the engine's `.gitignore` does not
ignore goes to the engine history, every other path to your data history when you have one (`--track`), and
the git hooks in `githooks/` (`git config core.hooksPath githooks`, which `init` sets) refuse a commit that
carries a home path, an address or a private IP.

## Uninstall

forge has no uninstall command. To remove it: delete the hook rows it wrote from `~/.claude/settings.json`
(their commands point into the checkout), delete the links in `~/.claude/skills` that point into it, delete the
project keys it wrote from `~/.claude.json`, delete each project's `.claude/settings.local.json` and `.codex/`,
and then the checkout. `forge sync` without `--apply` lists every file it would write.

## Not a fit?

forge is a per-machine registry. If you want per-repository config that travels with the repo, look at
[rulesync](https://github.com/dyoshikawa/rulesync) and [ruler](https://github.com/intellectronica/ruler).

Contributing: `CLAUDE.md` (also `AGENTS.md`) is the guide for working on the engine. License: MIT, see `LICENSE`;
third-party notices are in `NOTICE`.
