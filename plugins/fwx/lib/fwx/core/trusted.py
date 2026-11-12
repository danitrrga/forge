# copied-from: marshal-factory lib/trusted-checks.ts @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python and
# generalised past Node: a table of the files each executor reads, and the script a check runs.
"""What a PR must not change if its own checks are to count as proof.

The checks are trusted (their commands come from the recipe, `project.checks` in `.claude/fwx.json`), but a command is
only as honest as the files it runs. A PR that edits any of them hands the merge to a person, whatever its evidence says.
`trusted_edits` gives one reason per thing touched, and an empty list when the PR touches none:

- the recipe itself, `.claude/fwx.json`, and the CI workflows, `.github/workflows/**`, always;
- `package.json`, when a check runs `npm|pnpm|yarn|bun [run] <script>` and the change touches that script, one a script it
  calls, or one the head adds, or when there is nothing to compare (no patch and no versions);
- the files of an executor named in a check (EXECUTORS: `make` and the Makefile, `pytest` or `tox` and their config and
  every `conftest.py`, `nox`, `ruff`, `mypy`, `eslint`, `tsc`, `vitest`, `jest`);
- the first argument of a check when it is a path of the repo (`bin/fwx` of `python3 bin/fwx test`, `./scripts/x.sh`).

Changed files are paths, or dicts `{"path", "previous_path", "patch"}`: a rename out of a trusted file counts through
`previous_path`. Checks are commands, or dicts with a `command` (`project.checks`); None means the repo has no recipe and
its checks are the package.json scripts `test`, `lint`, `typecheck` and `build`. `package_json=(base_text, head_text)` gives
the two versions of package.json (None for one that could not be read) and compares the scripts exactly, following a script
that calls another and reading the commands of the scripts a check runs for their executors. Without it, package.json is
read from its patch alone, and a script is followed only through the lines the patch shows.

Declared limit, as in marshal: what a script runs inside is not followed. A shell script, a Makefile target or a package.json
script that calls another file is trusted as far as the name goes; the file it calls is not looked at. Settings kept in
`package.json` other than `scripts` (`eslintConfig`, `jest`) are not looked at either.

With a worktree setup configured (`setup`, the commands of `project.worktree_setup`, e.g. `npm ci`) the setup runs the package
manager in every worktree, and the package manager runs what the worktree under test holds: a `.npmrc`, the lockfiles, and the
install scripts of package.json (`preinstall`, `install`, `postinstall`, `prepare`). That happens before any person reads the diff,
so an edit of those files is a handover too (SETUP_INPUTS, LIFECYCLE). Not followed, the same declared limit: what an install
script of a dependency runs, a setup command that is not a package manager, and the manifests of other ecosystems than the
lockfiles named in SETUP_INPUTS (a `pyproject.toml` build backend, a `Cargo.toml` build script). `manifest=(base_text,
head_text)` gives the two versions of package.json for the install scripts; without it the patch of the entry is read.

Imports only `fwx.core.globs`.
"""
import fnmatch
import json
import os
import posixpath
import re
import shlex

from fwx.core import globs

RECIPE_PATH = ".claude/fwx.json"
WORKFLOWS = [".github/workflows/**"]
PACKAGE_JSON = "package.json"
DEFAULT_CHECKS = ("test", "lint", "typecheck", "build")
# What a worktree setup installs from, by file name at any depth, and the package.json scripts the package manager runs by itself.
SETUP_INPUTS = (".npmrc", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "uv.lock",
                "poetry.lock", "Pipfile.lock", "Gemfile.lock", "composer.lock", "requirements*.txt")
LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "preprepare", "postprepare")

# One row per executor: (name, the words of a command that run it, the files it reads). A glob with a leading `**/`
# also names the root. A new executor is a new row.
EXECUTORS = [
    ("make", ("make", "gmake"), ["**/Makefile", "**/GNUmakefile", "**/makefile"]),
    ("pytest", ("pytest", "py.test", "tox"), ["pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", "**/conftest.py"]),
    ("nox", ("nox",), ["noxfile.py"]),
    ("ruff", ("ruff",), ["ruff.toml", ".ruff.toml", "pyproject.toml"]),
    ("mypy", ("mypy",), ["mypy.ini", ".mypy.ini", "setup.cfg", "pyproject.toml"]),
    ("eslint", ("eslint",), ["eslint.config.*", ".eslintrc", ".eslintrc.*", ".eslintignore"]),
    ("tsc", ("tsc",), ["**/tsconfig.json", "**/tsconfig.*.json"]),
    ("vitest", ("vitest",), ["vitest.config.*", "vitest.workspace.*", "vite.config.*"]),
    ("jest", ("jest",), ["jest.config.*", "jest.setup.*"]),
]

RUNS_SCRIPT = re.compile(r"\b(?:bun|npm|pnpm|yarn)\s+(?:run\s+)?(\w[\w:.-]*)")
_ENV = re.compile(r"[A-Za-z_]\w*=")
_INTERPRETER = re.compile(r"(?:python[\d.]*|py|bash|sh|zsh|dash|fish|node|bun|deno|ruby|perl|php|tsx|ts-node)\Z")
_SCRIPT_EXT = re.compile(r"\.(?:sh|bash|py|js|mjs|cjs|ts|rb|pl)\Z")
_JSON_ENTRY = re.compile(r'\s*"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*\Z')


def scripts_of(package_json):
    """The string-valued `scripts` of a package.json text; None when it is missing or not JSON."""
    if package_json is None:
        return None
    try:
        data = json.loads(package_json)
    except ValueError:
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return {}
    return {k: v for k, v in scripts.items() if isinstance(v, str)}


def used_scripts(commands, *versions):
    """The scripts the commands run in any of these versions, following one script calling another. A script only one
    version has counts too, so adding one is as visible as changing one."""
    used = set()
    queue = list(commands)
    while queue:
        command = queue.pop()
        for m in RUNS_SCRIPT.finditer(command):
            name = m.group(1)
            if name in used:
                continue
            bodies = [v[name] for v in versions if v and name in v]
            if not bodies:
                continue
            used.add(name)
            queue.extend(bodies)
    return sorted(used)


def _norm(path):
    path = posixpath.normpath(path)
    return path[2:] if path.startswith("./") else path


def _commands(checks):
    if checks is None:
        return ["npm run %s" % name for name in DEFAULT_CHECKS]
    out = []
    for check in checks:
        command = check.get("command") if isinstance(check, dict) else check
        if not isinstance(command, str):
            raise ValueError("a check is a command or a dict with a command, got %r" % (check,))
        out.append(command)
    return out


def _touched(changed_files):
    """(the paths touched, in order, once each; the patch of package.json or None)."""
    paths, patch = [], None
    for entry in changed_files:
        entry = {"path": entry} if isinstance(entry, str) else entry
        for key in ("path", "previous_path"):
            if isinstance(entry.get(key), str) and entry[key] and _norm(entry[key]) not in paths:
                paths.append(_norm(entry[key]))
        if isinstance(entry.get("path"), str) and _norm(entry["path"]) == PACKAGE_JSON and isinstance(entry.get("patch"), str):
            patch = entry["patch"]
    return paths, patch


def _patch_view(patch):
    """({key: values} of every `"key": "value"` line the patch shows, the keys whose line it adds or removes)."""
    seen, changed = {}, set()
    for line in patch.splitlines():
        if line[:1] not in (" ", "+", "-") or line.startswith(("+++", "---")):
            continue
        m = _JSON_ENTRY.match(line[1:])
        if not m:
            continue
        try:
            value = json.loads('"%s"' % m.group(2))
        except ValueError:
            value = m.group(2)
        seen.setdefault(m.group(1), []).append(value)
        if line[0] != " ":
            changed.add(m.group(1))
    return seen, changed


def _segments(command):
    """The commands of a shell line split at `&&`, `||`, `;`, `|` and `&`, each as its words."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    segments, current = [], []
    for token in tokens:
        if token and all(c in "&|;()" for c in token):
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return [seg for seg in segments if seg]


def _script_path(words):
    """The repo path a command starts with: its first word, or the first argument of an interpreter; else None."""
    i = 0
    while i < len(words) and _ENV.match(words[i]):
        i += 1
    if i >= len(words):
        return None
    first = words[i]
    if _INTERPRETER.match(os.path.basename(first)):
        j = i + 1
        while j < len(words) and words[j].startswith("-"):
            if words[j] in ("-m", "-c", "-e", "-p"):
                return None
            j += 1
        if j >= len(words):
            return None
        first = words[j]
    if first.startswith(("/", "~", "-")) or "://" in first:
        return None
    if "/" in first or _SCRIPT_EXT.search(first):
        return _norm(first)
    return None


def _runs(command, word):
    return re.search(r"(?<![\w.-])%s(?![\w-])" % re.escape(word), command) is not None


def _list(files):
    return "%s%s" % (", ".join(files[:3]), " and %d more" % (len(files) - 3) if len(files) > 3 else "")


def _setup_reasons(touched, patch, setup, manifest):
    """The handovers for the files the worktree setup `setup` installs from."""
    reasons = []
    inputs = [f for f in touched if any(fnmatch.fnmatchcase(posixpath.basename(f), n) for n in SETUP_INPUTS)]
    if inputs:
        reasons.append("The pull request edits %s, which the worktree setup `%s` installs from and runs." % (_list(inputs), setup[0]))
    if PACKAGE_JSON in touched:
        changed = None
        if manifest is not None:
            base, head = scripts_of(manifest[0]), scripts_of(manifest[1])
            if base is not None and head is not None:
                changed = [n for n in LIFECYCLE if base.get(n) != head.get(n)]
        elif patch is not None:
            changed = [n for n in sorted(_patch_view(patch)[1]) if n in LIFECYCLE]
        if changed is None:
            reasons.append("The pull request edits package.json, and the install scripts the worktree setup `%s` runs couldn't be compared "
                           "with the base branch's." % setup[0])
        elif changed:
            reasons.append("The pull request edits the install scripts the worktree setup `%s` runs: %s." %
                           (setup[0], ", ".join("package.json scripts.%s" % n for n in changed)))
    return reasons


def trusted_edits(changed_files, checks, package_json=None, setup=(), manifest=None):
    """Why this PR edits what its checks trust, one reason each; empty when it doesn't. `setup` and `manifest` are in the module's
    docstring: without a setup they change nothing."""
    touched, patch = _touched(changed_files)
    commands = _commands(checks)
    reasons = []
    if RECIPE_PATH in touched:
        reasons.append("The pull request edits the recipe its checks come from: %s." % RECIPE_PATH)
    workflows = [f for f in touched if globs.matches_any(f, WORKFLOWS)]
    if workflows:
        reasons.append("The pull request edits CI workflows (%s)." % _list(workflows))

    scan = list(commands)
    if PACKAGE_JSON in touched and any(RUNS_SCRIPT.search(c) for c in commands):
        if package_json is not None:
            base, head = scripts_of(package_json[0]), scripts_of(package_json[1])
            if base is None or head is None:
                reasons.append("The pull request edits package.json, and its scripts couldn't be compared with the base branch's.")
            else:
                used = used_scripts(commands, base, head)
                changed = [n for n in used if base.get(n) != head.get(n)]
                scan += [v[n] for n in used for v in (base, head) if n in v]
                if changed:
                    reasons.append("The pull request edits the check scripts its checks run: %s." %
                                   ", ".join("package.json scripts.%s" % n for n in changed))
        elif patch is None:
            reasons.append("The pull request edits package.json, and its scripts couldn't be compared with the base branch's.")
        else:
            seen, changed = _patch_view(patch)
            used, queue = set(), list(commands)
            while queue:
                for m in RUNS_SCRIPT.finditer(queue.pop()):
                    if m.group(1) in seen and m.group(1) not in used:
                        used.add(m.group(1))
                        queue.extend(seen[m.group(1)])
            hit = sorted(used & changed)
            if hit:
                reasons.append("The pull request edits the check scripts its checks run: %s." %
                               ", ".join("package.json scripts.%s" % n for n in hit))

    for name, words, files in EXECUTORS:
        command = next((c for c in scan if any(_runs(c, w) for w in words)), None)
        if command is None:
            continue
        edited = [f for f in touched if globs.matches_any(f, files)]
        if edited:
            reasons.append("The pull request edits %s, which `%s` reads (%s)." % (_list(edited), command, name))

    if setup:
        reasons += _setup_reasons(touched, patch, setup, manifest)

    paths = {}
    for command in scan:
        for words in _segments(command):
            path = _script_path(words)
            if path is not None and path in touched and path not in paths:
                paths[path] = command
    for path, command in paths.items():
        reasons.append("The pull request edits %s, which the check `%s` runs." % (path, command))
    return reasons
