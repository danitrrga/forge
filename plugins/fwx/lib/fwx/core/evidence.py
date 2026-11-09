# copied-from: marshal-factory lib/evidence.ts:96-139 and :211-232 @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python:
# checks are the recipe's commands (marshal also named them), and the evidence is the row `facts.evidence` carries.
"""The checks a project defines, and what its evidence proves about the head commit.

`plan_checks(project_checks, repo_root)` is the effective recipe: the commands of the profile (`project.checks` in
`.claude/fwx.json`, plain commands or dicts with a `command`), and, when the profile has none, the package.json scripts
`test`, `lint`, `typecheck` and `build` run with the package manager of the lockfile (bun, then pnpm, yarn, npm; npm when
there is none). Empty when neither exists. Setup (an install) is not part of it: a checkout installs before it checks.

`evidence_state(evidence, head_sha, required)` is `headEvidence`, on the shape of `facts.evidence`: `{"sha", "clean",
"commands": [{"cmd", "rc"}]}`. `required` is the effective recipe, or None when the caller knows none. It returns a dict
with `state` and what the state names:

- `no_checks`: the recipe is empty, or (no recipe) the evidence ran no command. Decided before any evidence is looked at.
- `missing`: no evidence. `stale` (`sha`): evidence of another commit, so it proves nothing about this one.
- `dirty` (`sha`): the tree held more than the commit.
- `incomplete` (`missing`): commands of the recipe the evidence did not run.
- `untrusted` (`mismatched`, `missing`): it ran commands outside the recipe and left some of the recipe's out, so an agent
  that swapped `test` for `true` proves nothing. Commands outside the recipe that pass are not compared (a setup step).
- `failed` (`failed`, `passed`, `total`): a command exited non-zero or never exited, whether or not the recipe lists it.
- `verified` (`passed`, `total`).

The order is the order of that list; a command matches its recipe entry once surrounding whitespace is stripped. A malformed
evidence row is a ValueError, never a state: `decide` validates `facts` before it gets here.

Imports only `fwx.core.trusted`.
"""
import json
import os

from fwx.core import trusted

# Lockfile names and the runner they mean, in the order they are tried.
PACKAGE_MANAGERS = [
    (("bun.lock", "bun.lockb"), "bun run"),
    (("pnpm-lock.yaml",), "pnpm run"),
    (("yarn.lock",), "yarn run"),
    (("package-lock.json",), "npm run"),
]
DEFAULT_RUNNER = "npm run"


def _commands(checks):
    """The non-blank commands of a list of checks (strings, or dicts with a `command`), stripped."""
    out = []
    for check in checks or []:
        command = check.get("command") if isinstance(check, dict) else check
        if not isinstance(command, str):
            raise ValueError("a check is a command or a dict with a command, got %r" % (check,))
        if command.strip():
            out.append(command.strip())
    return out


def plan_checks(project_checks, repo_root):
    """The effective recipe, a list of commands: the profile's, else the package.json scripts, else []."""
    recipe = _commands(project_checks)
    if recipe:
        return recipe
    try:
        with open(os.path.join(repo_root, trusted.PACKAGE_JSON), encoding="utf-8") as f:
            scripts = trusted.scripts_of(f.read())
    except (OSError, UnicodeDecodeError):
        return []
    names = [name for name in trusted.DEFAULT_CHECKS if name in (scripts or {})]
    if not names:
        return []
    runner = next((run for locks, run in PACKAGE_MANAGERS
                   if any(os.path.exists(os.path.join(repo_root, lock)) for lock in locks)), DEFAULT_RUNNER)
    return ["%s %s" % (runner, name) for name in names]


def _rows(evidence):
    """(sha, clean, [(cmd, rc)]) of an evidence row, checked."""
    sha, clean, commands = evidence.get("sha"), evidence.get("clean"), evidence.get("commands")
    if not isinstance(sha, str) or not isinstance(clean, bool) or not isinstance(commands, list):
        raise ValueError("evidence needs a string sha, a boolean clean and a list of commands, got %r" % (evidence,))
    rows = []
    for c in commands:
        cmd, rc = (c.get("cmd"), c.get("rc")) if isinstance(c, dict) else (None, None)
        if not isinstance(cmd, str) or (rc is not None and (not isinstance(rc, int) or isinstance(rc, bool))) \
                or "rc" not in c:
            raise ValueError("a command of the evidence is {cmd: string, rc: integer or null}, got %r" % (c,))
        rows.append((cmd.strip(), rc))
    return sha, clean, rows


def evidence_state(evidence, head_sha, required):
    """What `evidence` proves about `head_sha` against the recipe `required` (a list of checks, or None)."""
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError("head_sha is the commit's full sha, got %r" % (head_sha,))
    recipe = None if required is None else _commands(required)
    if recipe == []:
        return {"state": "no_checks"}
    if not isinstance(evidence, dict) or not evidence:
        return {"state": "missing"}
    sha, clean, rows = _rows(evidence)
    if sha != head_sha:
        return {"state": "stale", "sha": sha}
    if recipe is None and not rows:
        return {"state": "no_checks"}
    if not clean:
        return {"state": "dirty", "sha": sha}
    ran = [cmd for cmd, _ in rows]
    missing = [c for c in recipe or [] if c not in ran]
    if missing:
        outside = [cmd for cmd in dict.fromkeys(ran) if cmd not in recipe]
        if outside:
            return {"state": "untrusted", "sha": sha, "mismatched": outside, "missing": missing}
        return {"state": "incomplete", "sha": sha, "missing": missing}
    failed = [cmd for cmd, rc in rows if rc != 0]
    total = len(rows)
    if failed:
        return {"state": "failed", "sha": sha, "failed": list(dict.fromkeys(failed)), "passed": total - len(failed),
                "total": total}
    return {"state": "verified", "sha": sha, "passed": total, "total": total}
