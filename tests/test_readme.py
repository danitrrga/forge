#!/usr/bin/env python3
"""The claims of README.md and CLAUDE.md that a machine can check, checked against the engine itself:

- the Commands block of README.md names every `forge` subcommand (less the hook-only `session-start`) and no other;
- every skill-bench subcommand README.md shows exists in scripts/bench/skill_bench.py;
- every engine path the two files name in backticks (forge/, scripts/, hooks/, tests/, githooks/, examples/, bin/,
  benchmarks/skill-bench/, docs/assets/, .github/) exists in this checkout;
- every UPPER_CASE name they put in backticks is assigned somewhere in the engine's Python;
- every <img> in README.md points at a file that exists and carries alt text of at least 40 characters, and every
  <source srcset> (the dark-theme image of a <picture>) points at a file that exists;
- no named branch is called "on a branch", "not merged" or "unmerged" while it is an ancestor of the default branch
  (`git merge-base --is-ancestor`). Where git cannot say (the branch is gone, there is no default branch to compare with,
  or a shallow checkout answered "not an ancestor", which a cut history cannot prove), the claim is reported as
  `NOT RUN, NOT ARMED` and the test exits 77 unless something failed.

The paths of a user's data (config/forge.json, credentials/, skills/) are not engine files and are not checked.
Controls (control_cases): a README with a made-up subcommand, a missing one, a dead path, an unknown constant and an
image with no alt text each make the matching check fail, and reading zero paths or constants is a failure. The branch
check has its own controls on a toy repository (branch_controls): a merged branch called unmerged fails, an unmerged one
passes, a deleted branch and a shallow clone are NOT RUN. Seen failing against the README of 038d327, which called
feat/3.2-session and feat/3.5-ui-walk "on a branch, not merged" while both were ancestors of master:
  FAIL README.md says `feat/3.2-session` is "on a branch" / "not merged", but it is an ancestor of master (git
  merge-base --is-ancestor exits 0): it is merged. Say what runs today, built and on the default branch, and name the file
  or command that proves it; do not name the branch."""
import argparse
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from forge import cli  # noqa: E402

FORGE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ENGINE_PREFIXES = ("forge/", "scripts/", "hooks/", "tests/", "githooks/", "examples/", "bin/", "benchmarks/skill-bench/",
                   "docs/assets/", ".github/")
HOOK_ONLY = {"session-start"}
failures = []
not_run = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def read(rel):
    with open(os.path.join(FORGE, rel), encoding="utf-8") as fh:
        return fh.read()


def subcommands():
    """The subcommand names bin/forge's parser accepts, read from the parser forge/cli.py builds."""
    names = set()
    orig = argparse.ArgumentParser.parse_args
    try:
        def grab(self, *a, **k):
            for act in self._actions:
                if isinstance(act, argparse._SubParsersAction):
                    names.update(act.choices)
            raise SystemExit(0)
        argparse.ArgumentParser.parse_args = grab
        try:
            cli.main(["--help"])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = orig
    return names


def commands_block(text):
    m = re.search(r"^## Commands\n+```\n(.*?)\n```", text, re.S | re.M)
    return {l.split()[1] for l in m.group(1).splitlines() if l.startswith("forge ")} if m else set()


def bench_subcommands():
    """The subcommands skill_bench.py's own --help lists ({validate,list,...})."""
    r = subprocess.run([sys.executable, os.path.join(FORGE, "scripts", "bench", "skill_bench.py"), "--help"],
                       capture_output=True, text=True)
    m = re.search(r"\{([a-z,]+)\}", r.stdout)
    return set(m.group(1).split(",")) if m else set()


def named_paths(text):
    out = set()
    for tok in re.findall(r"`([^`\s]+)`", text):
        tok = tok.rstrip(".,:;)")
        if tok.startswith(ENGINE_PREFIXES) and "<" not in tok and "*" not in tok:
            out.add(tok)
    return out


def named_constants(text):
    return {t for t in re.findall(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]+)`", text)}


def engine_python():
    chunks = []
    for top in ("forge", "scripts", "hooks", "bin"):
        for d, _, files in os.walk(os.path.join(FORGE, top)):
            for f in files:
                p = os.path.join(d, f)
                if f.endswith(".py") or (top == "bin" and f == "forge"):
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        chunks.append(fh.read())
    return "\n".join(chunks)


def check(readme, claude_md, subs, bench, exists, python_src, label=""):
    """The failures (as label strings) of one README/CLAUDE.md pair."""
    before = len(failures)
    want(label + "README Commands block = the CLI's subcommands", sorted(commands_block(readme)), sorted(subs - HOOK_ONLY))
    shown = set(re.findall(r"skill_bench\.py ([a-z]+)", readme))
    want(label + "skill-bench subcommands the README shows, missing from skill_bench.py", sorted(shown - bench), [])
    paths = named_paths(readme) | named_paths(claude_md)
    want(label + "engine paths named and missing", sorted(p for p in paths if not exists(p.rstrip("/"))), [])
    consts = named_constants(readme) | named_constants(claude_md)
    want(label + "constants named and never assigned",
         sorted(c for c in consts if not re.search(r"^\s*%s\s*=" % re.escape(c), python_src, re.M)), [])
    want(label + "read at least one path and one constant", bool(paths) and bool(consts), True)
    for src, alt in re.findall(r'<img src="([^"]+)" alt="([^"]*)"', readme):
        want(label + "image %s exists" % src, exists(src), True)
        want(label + "image %s has alt text of 40+ characters" % src, len(alt) >= 40, True)
    for src in re.findall(r'<source [^>]*srcset="([^"]+)"', readme):
        want(label + "dark-theme image %s exists" % src, exists(src), True)
    return failures[before:]


def control_cases(readme, claude_md, subs, bench, exists, python_src):
    """Each plant makes its check fail, then the plants are dropped from the failure list."""
    plants = (
        ("a made-up subcommand", readme.replace("forge test [fwx] [--mutants]", "forge test [fwx] [--mutants]\nforge teleport", 1),
         claude_md, "Commands block"),
        ("a missing subcommand", re.sub(r"^forge lock .*\n", "", readme, flags=re.M), claude_md, "Commands block"),
        ("a dead path", readme + "\n`forge/no_such_module.py`\n", claude_md, "engine paths named and missing"),
        ("an unknown constant", readme, claude_md + "\n`NO_SUCH_TABLE`\n", "constants named and never assigned"),
        ("an image with no alt text", readme + '\n<img src="docs/assets/none.png" alt="">\n', claude_md, "has alt text"),
        ("a dark-theme image that is not there",
         readme + '\n<source media="(prefers-color-scheme: dark)" srcset="docs/assets/none-dark.png">\n', claude_md,
         "dark-theme image"),
        ("zero paths and constants", "## Commands\n\n```\n```\n", "", "read at least one path"))
    for name, r, c, needle in plants:
        got = check(r, c, subs, bench, exists, python_src, label="[control: %s] " % name)
        del failures[len(failures) - len(got):]
        want("control %s fails its check" % name, any(needle in g for g in got), True)


# ---- a named branch called "on a branch" / "not merged" / "unmerged" while it is merged ----

UNMERGED_CLAIM = re.compile(r"\bon (?:a|its own|the) branch\b|\bon branches\b|\bnot (?:yet )?merged\b|\bunmerged\b", re.I)
BRANCH_LIKE = re.compile(r"^(?:feat|fix|chore|docs|test|refactor)/[A-Za-z0-9._-]+$")


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)


def blocks(text):
    """README paragraphs and list items, whitespace collapsed: a claim and the branch it names sit in one block."""
    out, cur = [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith(("- ", "#", "|", "```")):
            if cur:
                out.append(" ".join(cur))
            cur = [] if not line.strip() else [line.strip()]
        else:
            cur.append(line.strip())
    if cur:
        out.append(" ".join(cur))
    return [" ".join(b.split()) for b in out]


def branch_claims(text, root):
    """(branch, block) for each backticked branch name in a block that says "on a branch", "not merged" or "unmerged".
    A token is a branch when a ref of that name exists here or it is written like one (feat/..., fix/..., docs/...) and is not a file."""
    found = []
    for b in blocks(text):
        if not UNMERGED_CLAIM.search(b):
            continue
        for tok in re.findall(r"`([^`\s]+)`", b):
            if os.path.exists(os.path.join(root, tok)):
                continue
            if BRANCH_LIKE.match(tok) or git(root, "rev-parse", "--verify", "-q", "refs/heads/" + tok).returncode == 0:
                found.append((tok, b))
    return found


def default_branch(root):
    """The ref the work merges into: local master or main, else origin's (origin/HEAD's target first); None when none exists."""
    r = git(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    cands = ["master", "main"] + ([r.stdout.strip()] if r.returncode == 0 and r.stdout.strip() else []) + ["origin/master", "origin/main"]
    for c in cands:
        if git(root, "rev-parse", "--verify", "-q", "refs/heads/%s^{commit}" % c).returncode == 0 or \
                git(root, "rev-parse", "--verify", "-q", "refs/remotes/%s^{commit}" % c).returncode == 0:
            return c
    return None


def judge(root, branch):
    """("merged", why) | ("unmerged", why) | ("unknown", why). Only exit 0 of merge-base is proof in a cut history."""
    base = default_branch(root)
    if base is None:
        return "unknown", "there is no master or main here to compare with"
    ref = next((r for r in ("refs/heads/" + branch, "refs/remotes/origin/" + branch)
                if git(root, "rev-parse", "--verify", "-q", r + "^{commit}").returncode == 0), None)
    if ref is None:
        return "unknown", "branch %s no longer exists here, so whether it was merged cannot be read" % branch
    rc = git(root, "merge-base", "--is-ancestor", ref, base).returncode
    if rc == 0:
        return "merged", base
    shallow = git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    if rc == 1 and not shallow:
        return "unmerged", base
    return "unknown", "%s is a shallow checkout (set fetch-depth: 0)" % branch if shallow else "git merge-base exited %d" % rc


def check_branch_claims(text, root, label=""):
    """Returns (failures, not_run, claims read); the callers append them."""
    fails, skipped, claims = [], [], branch_claims(text, root)
    for branch, block in claims:
        verdict, why = judge(root, branch)
        if verdict == "merged":
            fails.append('%sREADME.md says `%s` is "on a branch" / "not merged", but it is an ancestor of %s (git merge-base '
                         '--is-ancestor exits 0): it is merged. Say what runs today, built and on the default branch, and name '
                         'the file or command that proves it; do not name the branch. The sentence: "%s"'
                         % (label, branch, why, block if len(block) <= 200 else block[:200].rsplit(" ", 1)[0] + " ..."))
        elif verdict == "unknown":
            skipped.append("%s%s: %s" % (label, branch, why))
    return fails, skipped, len(claims)


def branch_controls():
    """A toy repository: master c1..c3, feat/merged at c1, feat/ahead one commit past master; then a clone cut to depth 1."""
    def run(root, *a):
        r = git(root, *a)
        if r.returncode != 0:
            failures.append("toy git %s failed: %s" % (" ".join(a), r.stderr.strip()))
        return r
    claim = 'The session skill is on a branch, not merged (`%s`).'
    with tempfile.TemporaryDirectory() as tmp:
        repo, clone = os.path.join(tmp, "repo"), os.path.join(tmp, "clone")
        os.mkdir(repo)
        run(repo, "init", "-q", "-b", "master")
        for k in ("user.name", "user.email"):
            run(repo, "config", k, "toy@example.test")
        for i in (1, 2, 3):
            run(repo, "commit", "-q", "--allow-empty", "-m", "c%d" % i)
            if i == 1:
                run(repo, "branch", "feat/merged")
        run(repo, "checkout", "-q", "-b", "feat/ahead")
        run(repo, "commit", "-q", "--allow-empty", "-m", "ahead")
        run(repo, "checkout", "-q", "master")
        run(repo, "branch", "feat/gone")
        run(repo, "branch", "-D", "feat/gone")
        got = lambda name, root: check_branch_claims(claim % name, root, label="[control: %s] " % name)
        f, n, c = got("feat/merged", repo)
        want("control: a merged branch called unmerged fails", (len(f), len(n), c), (1, 0, 1))
        want("control: the failure says what to write", "name the file or command that proves it" in "".join(f), True)
        f, n, c = got("feat/ahead", repo)
        want("control: an unmerged branch called unmerged passes", (len(f), len(n), c), (0, 0, 1))
        f, n, c = got("feat/gone", repo)
        want("control: a branch that no longer exists is NOT RUN, not a pass or a fail", (len(f), len(n), c), (0, 1, 1))
        f, n, c = check_branch_claims("Built and merged, on the default branch (`feat/merged`).", repo)
        want("control: a merged branch named without the claim is not a finding", (len(f), len(n), c), (0, 0, 0))
        run(tmp, "clone", "-q", "--depth", "1", "--no-single-branch", "file://" + repo, clone)
        want("control: the clone is shallow", git(clone, "rev-parse", "--is-shallow-repository").stdout.strip(), "true")
        f, n, c = got("feat/merged", clone)
        want("control: a shallow clone that cannot see the ancestry is NOT RUN, not a fail", (len(f), len(n), c), (0, 1, 1))
        f, n, c = got("feat/ahead", clone)
        want("control: a shallow clone cannot prove a branch unmerged either: NOT RUN, not a pass", (len(f), len(n), c), (0, 1, 1))
        lone = os.path.join(tmp, "lone")
        os.mkdir(lone)
        run(lone, "init", "-q", "-b", "trunk")
        f, n, c = got("feat/merged", lone)
        want("control: no master or main to compare with is NOT RUN", (len(f), len(n)), (0, 1))


def main():
    readme, claude_md = read("README.md"), read("CLAUDE.md")
    subs, bench, src = subcommands(), bench_subcommands(), engine_python()
    want("read the CLI's subcommands", len(subs) > 5, True)
    want("read skill_bench.py's subcommands", "validate" in bench, True)

    def exists(rel):
        return os.path.exists(os.path.join(FORGE, rel))

    check(readme, claude_md, subs, bench, exists, src)
    control_cases(readme, claude_md, subs, bench, exists, src)
    branch_controls()
    f, skipped, branch_claims_read = check_branch_claims(readme, FORGE)
    failures.extend(f)
    not_run.extend(skipped)
    for f in failures:
        print("FAIL " + f)
    print("%d subcommand(s), %d path(s), %d constant(s) read; %d failure(s)"
          % (len(subs), len(named_paths(readme) | named_paths(claude_md)),
             len(named_constants(readme) | named_constants(claude_md)), len(failures)))
    print("%d branch claim(s) read in README.md" % branch_claims_read)
    if failures:
        sys.exit(1)
    if not_run:  # exit 77: `forge test` shows NOT RUN, NOT ARMED, never a PASS
        for n in not_run:
            print("NOT RUN, NOT ARMED: " + n)
        sys.exit(77)


if __name__ == "__main__":
    main()
