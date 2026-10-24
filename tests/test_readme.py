#!/usr/bin/env python3
"""The claims of README.md and CLAUDE.md that a machine can check, checked against the engine itself:

- the Commands block of README.md names every `forge` subcommand (less the hook-only `session-start`) and no other;
- every skill-bench subcommand README.md shows exists in scripts/bench/skill_bench.py;
- every engine path the two files name in backticks (forge/, scripts/, hooks/, tests/, githooks/, examples/, bin/,
  benchmarks/skill-bench/, docs/assets/, .github/) exists in this checkout;
- every UPPER_CASE name they put in backticks is assigned somewhere in the engine's Python;
- every <img> in README.md points at a file that exists and carries alt text of at least 40 characters, and every
  <source srcset> (the dark-theme image of a <picture>) points at a file that exists.

The paths of a user's data (config/forge.json, credentials/, skills/) are not engine files and are not checked.
Controls (control_cases): a README with a made-up subcommand, a missing one, a dead path, an unknown constant and an
image with no alt text each make the matching check fail, and reading zero paths or constants is a failure."""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from forge import cli  # noqa: E402

FORGE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ENGINE_PREFIXES = ("forge/", "scripts/", "hooks/", "tests/", "githooks/", "examples/", "bin/", "benchmarks/skill-bench/",
                   "docs/assets/", ".github/")
HOOK_ONLY = {"session-start"}
failures = []


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
        ("a made-up subcommand", readme.replace("forge test [--mutants]", "forge test [--mutants]\nforge teleport", 1),
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


def main():
    readme, claude_md = read("README.md"), read("CLAUDE.md")
    subs, bench, src = subcommands(), bench_subcommands(), engine_python()
    want("read the CLI's subcommands", len(subs) > 5, True)
    want("read skill_bench.py's subcommands", "validate" in bench, True)

    def exists(rel):
        return os.path.exists(os.path.join(FORGE, rel))

    check(readme, claude_md, subs, bench, exists, src)
    control_cases(readme, claude_md, subs, bench, exists, src)
    for f in failures:
        print("FAIL " + f)
    print("%d subcommand(s), %d path(s), %d constant(s) read; %d failure(s)"
          % (len(subs), len(named_paths(readme) | named_paths(claude_md)),
             len(named_constants(readme) | named_constants(claude_md)), len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
