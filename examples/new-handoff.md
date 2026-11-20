# Finish setting up {{NAME}} for the agent framework

You are a coding agent in {{FOLDER}}, a new `{{STACK}}` project that forge has just registered with the agent framework on. Three
fields cannot be known without looking at the project, so forge left them unset, and `forge doctor {{NAME}}` says `NOT RUN, NOT ARMED`
for them until they are set.

## Goal

Propose a value for each of the three fields below, each checked by running it here, and hand them back as one JSON block. Write
nothing in forge: the project's file (`config/projects/{{NAME}}.claude.json`) is forge's data, and its owner pastes your block into it.

## Interview the user

Read the project first (its manifest, scripts, CI file and folders) and ask only what the files do not answer, one question at a
time, each with your proposal and why:

- Which files must always go to a person to review and never to an unattended run (secrets, deploy and infrastructure files,
  lockfiles, the build configuration)?
- Which commands build or type-check the project in seconds, without the full test suite?
- Does it have a screen a person looks at? If so, how is it started on this machine, and what shows it is ready?

## The three values

For each: the proposed value, and the command you ran to check it with what it returned.

- `protected_paths`: a list of globs, relative to the project root. Check: each glob matches at least one tracked file
  (`git ls-files` with the glob) and none of them is `**` or `*`.
- `checks_quick`: a list of shell commands, each finishing in seconds and exiting 0 on the project as it is. They are what runs
  after every task of a wave; the slow, full checks are `checks` below. Check: run each one and report its exit code and time.
- `app_run`: an object `{"up", "run", "down", "url", "ready"}`: `up` starts the app in the background and returns, `run` is empty
  unless the app needs a command to run after it is up, `down` stops it, `url` is its root address (answers 2xx) and `ready` is a
  text only the logged-in page shows. Leave the field out when the project has no screen. Check: run `up`, request `url`, look for
  `ready`, run `down`, and confirm nothing is left listening.

`checks` is already set from the stack: {{CHECKS}}. Run each one here; if one does not run on this project, say so and propose its
replacement in the same block.

## Also

This folder has no `CLAUDE.md` or `AGENTS.md`, so the `instruction files` row of `forge doctor {{NAME}}` fails until the project has
one. Offer to write it; that is the project's own work and belongs in this repository.

## Hand back

One JSON block with only the keys you checked, for example:

```json
{"protected_paths": ["package.json"], "checks_quick": ["pnpm tsc --noEmit"]}
```

and, under it, one line per key with the command you ran and its result.
