# forge

forge generates the agent configuration of every project on a machine (Claude Code and, optionally,
Codex) from one checkout: MCP servers, skill and plugin trims, hooks, permissions and the shared
instruction document. This file is for an agent working **on the engine**. A user's own setup (skills,
profiles, `config/forge.json`, credentials) lives in the same folder but is data, ignored by the engine's
git; `README.md` is the user guide.

## Layout

```
bin/forge            the one entry point
forge/               the engine: lib, cli, sync, hooks, mcp, memory, skills, publish
scripts/sync/        the generators, each derives its root from __file__; scripts/metrics/ harness metrics
hooks/               the shared hooks that user-scope settings point at, with their tests
config/gsd/          prose payloads of the GSD patches
examples/            what `forge init` copies for a new user (forge.json, AGENT-SYSTEM.md, ...)
githooks/            the personal-data guard, enabled with `core.hooksPath githooks`
tests/               the suites; tests/sandbox.py builds a toy world
```

## Verifying a change

```bash
python3 bin/forge sync          # dry-run of every generator; --apply writes, --project NAME / --all set the scope
python3 bin/forge skills        # dry-run of the user-scope steps (skill links, GSD runtime); --apply writes
python3 bin/forge doctor        # one PASS/FAIL/SKIP line per check, exit 1 on a FAIL; `doctor NAME` scopes it to a project
python3 bin/forge test          # every tracked test_*.py at nice 19; `--mutants` runs only the on-demand guard mutants
python3 tests/test_<name>.py    # one suite: each is a plain script (no pytest) that prints its FAILs and exits 1 on any
python3 bin/forge check-public --all   # personal data in the engine files
```

Every generator is a dry-run until `--apply`. Dry-run first, `--apply` second, git commit between. Git is the
only rollback: a `.bak` file is written once, ever.

## Rules for a change

1. **Only the installed checkout writes.** `lib.may_write()` allows a write only from the checkout that the
   SessionStart hook in `~/.claude/settings.json` names. A git worktree, a plain copy elsewhere and a toy HOME
   write nothing. Anything that writes is tested in a toy world built with `tests/sandbox.py`, never against the
   real HOME or a real project.
2. **A change that should not alter generated output leaves the dry-run byte-identical.** Compare the dry-run
   output before and after with `cmp`. A change that alters output on purpose says exactly which line changes
   and why.
3. **A test never seen to fail is not evidence.** Write the test first, run it against the current code, and
   keep the failure message in the test comment and the commit message. Every new check carries a negative
   control that proves it can fail.
4. **A check says how much it looked at, and looking at zero is a failure** wherever zero is impossible. A check
   that could not run because a tool or a secret is missing prints `NOT RUN, NOT ARMED` and is neither a PASS
   nor a FAIL. A check that finds nothing to look at because the user switched that feature off is a SKIP with
   the same wording.
5. **Nothing personal in an engine file.** Names, home paths, addresses and project names belong in the user's
   `config/forge.json` and profiles, never in code, comments or tests. Fixtures use neutral names and the
   documentation ranges `192.0.2.0/24` and `198.51.100.0/24`.
6. **Generated files are never edited by hand:** `~/.claude.json`, any `.mcp.json`, a project's
   `.claude/settings.local.json`. Edit the source (`config/`, a profile, `forge/`) and run the generator.
7. **Never read, print or copy a value from `credentials/`.** `config/secrets.json` links to it and the
   registry refers to a secret as `${VAR}`.

## Optional integrations

Codex, GSD and Hindsight are switched on and off in `config/forge.json` (`integrations`). Code that
touches one reads `lib.on("<name>")`; with the integration off, forge writes none of its files and removes only
the entries it wrote itself (matched by exact command). A new feature that depends on an external tool needs a
switch, a SKIP line for the off state, and a FAIL naming the fix for on-but-broken.

`codex_harness` in `config/forge.json` (read only with Codex on, default false) says whether Codex is set up like
Claude Code: true, `forge sync` writes its hook rows into `~/.codex/hooks.json` and each project's MCP servers into
`.codex/config.toml`; false, it writes neither and takes out only what it wrote (hook entries by exact command, the
`[mcp_servers.<registry name>]` tables of `.codex/config.toml`, its `[shell_environment_policy]` table when it has the shape forge writes, and the `.bak` of that file when it holds forge's), keeping the `.agents/skills` links, and the `codex hooks`
row of `forge doctor` follows the switch.

## Committing

`forge commit -m MESSAGE (PATH... | --all)` sends each changed path to the history that owns it (the engine's, or the
user's own data history if they keep one) and prints each hash. With no path it refuses unless given `--all`, so one commit never sweeps in unrelated changes. The `githooks/` run `forge check-public` on the
staged files, the message and the pushed range, and refuse a commit that carries personal data. Use a
`docs(...)`, `fix(...)`, `test(...)` or `feat(...)` prefix, and describe what changed and why.

## Branches and CI

The default branch takes changes by pull request only: work on a branch (`feat/...`, `fix/...`, `chore/...`),
open a PR from the PR template, and merge when `All checks` is green. `.github/workflows/ci.yml` (from
`repo-kit/`) aggregates the engine's own checks in `checks.yml`, a secrets scan and a workflow audit (actionlint,
zizmor) into that one check; add a job to `checks.yml`, never to `ci.yml`. Every action is pinned by commit hash
(`zizmor.yml` enforces it). `repo-kit/kit.py ruleset --repo danitrrga/forge --apply` puts the same rule on GitHub.
Work in a git worktree, since only the installed checkout writes (rule 1).
`githooks/ci-local` runs the same checks on this machine in seconds (control: a planted AWS key in a commit makes
its gitleaks step, and so the script, fail); use it when Actions minutes are out.

## Where things go

- A new generator step goes in `forge/sync.py`'s sequence: the sequence is the output, and the output is an API.
- A new profile field gets a row in `lib.PROFILE_FIELDS`, so `profile_error` checks its type once.
- A new hook row goes in `forge/hooks.py`; a row that belongs to an integration is also listed in
  `ROW_INTEGRATION`.
- A skill is never part of the engine. Skills live in the user's `skills/<name>/SKILL.md`.
