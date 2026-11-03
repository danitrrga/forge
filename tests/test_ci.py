#!/usr/bin/env python3
"""The CI runs `python3 bin/fwx test` and no `uv`, and the repo carries no kit leftovers.

copied-from: none (the kit's own python-uv `checks.yml` is embedded below only as the control's input)

Checked on the repo's files, and on toy copies for the controls:
  - .github/workflows/checks.yml has a step `run: python3 bin/fwx test` (a commented-out one does not count);
  - no line of it outside comments mentions `uv` (setup-uv, `uv sync`, `uv run`);
  - there is no lefthook.yml or uv.toml (the hooks are githooks/; there is no pyproject.toml or uv.lock);
  - .github/dependabot.yml has no `uv` ecosystem (nothing for it to read; the entry would only error);
  - .github/workflows/ci.yml calls checks.yml, so the project's job is inside `All checks`.
A file that is missing, or a checks.yml with no line at all, is a failure.

Controls (each is the repo's files with one change, in a toy dir, and must fail its own check):
  - the checks.yml the kit's `render` writes, with `uv sync --locked` and `uv run pytest`
  - the same file with the fwx step added and the uv steps kept
  - a checks.yml whose fwx step is only a comment
  - a toy lefthook.yml, and a toy uv.toml
  - the kit's dependabot.yml, with its uv ecosystem
  - a ci.yml that does not call checks.yml
  - a toy dir with no checks.yml
  - a comment that says "uv" does not fail (the check is not a plain grep)
Seen red, each on a copy of this test with one check switched off (`if <check>:` made `if False:`), 14 checks each:
  - no fwx step (the render-written checks.yml and a commented-out step both pass it):
      FAIL: control the checks.yml render writes: fails with 'has no step': problems: ["checks.yml mentions uv: [...]"]
      FAIL: control a commented-out fwx step: fails with 'has no step': problems: []
  - a step that counts a commented-out line (`"bin/fwx test" in l` over every line):
      FAIL: control a commented-out fwx step: fails with 'has no step': problems: []
  - uv not looked for:
      FAIL: control the checks.yml render writes, uv: fails with 'mentions uv': problems: ['checks.yml has no step `run: python3 bin/fwx test`']
      FAIL: control the fwx step added, uv steps kept: fails with 'mentions uv': problems: []
  - uv looked for in comments too (a plain grep):
      FAIL: the repo's CI files: got ["checks.yml mentions uv: ['# copied-from: ... checks.yml @582258b', '# Adapted: the uv steps became ...']"], want []
      FAIL: a comment that says uv does not fail: got ["checks.yml mentions uv: ['# no uv here, and no `uv run`', ...]"], want []
  - lefthook.yml and uv.toml not looked for:
      FAIL: control a toy lefthook.yml: fails with 'lefthook.yml exists': problems: []
      FAIL: control a toy uv.toml: fails with 'uv.toml exists': problems: []
  - the dependabot uv ecosystem not looked for:
      FAIL: control the kit's dependabot.yml: fails with 'uv ecosystem': problems: []
  - ci.yml not checked for the call to checks.yml:
      FAIL: control a ci.yml that does not call checks.yml: fails with 'does not call checks.yml': problems: []
  - a missing file not reported:
      FAIL: control no checks.yml: fails with 'checks.yml is missing': problems: []
  - zero lines not reported:
      FAIL: control an empty checks.yml: fails with 'no line that is not a comment': problems: ['checks.yml has no step `run: python3 bin/fwx test`']
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

FWX_STEP = re.compile(r"^\s*-\s+run:\s+python3 bin/fwx test\s*$")
UV = re.compile(r"\buv\b")
KIT_CHECKS = """name: Project checks
on:
  workflow_call:
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0
      - run: uv sync --locked
      # pytest exits 5 when it collects no tests, so an empty project is red, not falsely green.
      - run: uv run pytest
"""
KIT_DEPENDABOT = """version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
  - package-ecosystem: "github-actions"
    directory: "/"
"""


def code_lines(text):
    return [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def problems(root):
    out = []
    checks, ci, dependabot = (read(root, ".github/workflows/checks.yml"), read(root, ".github/workflows/ci.yml"),
                              read(root, ".github/dependabot.yml"))
    for rel, text in ((".github/workflows/checks.yml", checks), (".github/workflows/ci.yml", ci),
                      (".github/dependabot.yml", dependabot)):
        if text is None:
            out.append("%s is missing" % rel)
    if checks is not None:
        lines = code_lines(checks)
        if not lines:
            out.append("checks.yml has no line that is not a comment")
        if not any(FWX_STEP.match(l) for l in lines):
            out.append("checks.yml has no step `run: python3 bin/fwx test`")
        uv = [l.strip() for l in lines if UV.search(l)]
        if uv:
            out.append("checks.yml mentions uv: %s" % uv)
    for rel in ("lefthook.yml", "uv.toml"):
        if os.path.exists(os.path.join(root, rel)):
            out.append("%s exists" % rel)
    if dependabot is not None and re.search(r'package-ecosystem:\s*"?uv\b', "\n".join(code_lines(dependabot))):
        out.append("dependabot.yml has a uv ecosystem")
    if ci is not None and not re.search(r"^\s*uses:\s*\./\.github/workflows/checks\.yml\b", "\n".join(code_lines(ci)), re.M):
        out.append("ci.yml does not call checks.yml")
    return out


s = helpers.Suite()
s.eq("the repo's CI files", problems(helpers.ROOT), [])
looked = code_lines(read(helpers.ROOT, ".github/workflows/checks.yml") or "")
s.ok("the repo's checks.yml has lines to look at", len(looked) > 5, "%d lines" % len(looked))

toy = helpers.mkdtemp("fwx-ci-")
for rel in (".github/workflows/checks.yml", ".github/workflows/ci.yml", ".github/dependabot.yml"):
    os.makedirs(os.path.dirname(os.path.join(toy, rel)), exist_ok=True)
    shutil.copy(os.path.join(helpers.ROOT, rel), os.path.join(toy, rel))
s.eq("a toy copy of the CI files", problems(toy), [])


def control(name, needle, files=None, remove=()):
    """A toy copy of the files with `files` ({rel: text}) written over it and `remove` taken out."""
    d = helpers.mkdtemp("fwx-ci-c-")
    shutil.copytree(os.path.join(toy, ".github"), os.path.join(d, ".github"))
    for rel, text in (files or {}).items():
        helpers.write(d, rel, text)
    for rel in remove:
        os.remove(os.path.join(d, rel))
    got = problems(d)
    s.ok("control %s: fails with %r" % (name, needle), any(needle in g for g in got), "problems: %r" % got)
    return got


control("the checks.yml render writes", "has no step", {".github/workflows/checks.yml": KIT_CHECKS})
control("the checks.yml render writes, uv", "mentions uv", {".github/workflows/checks.yml": KIT_CHECKS})
control("the fwx step added, uv steps kept", "mentions uv",
        {".github/workflows/checks.yml": KIT_CHECKS + "      - run: python3 bin/fwx test\n"})
control("a commented-out fwx step", "has no step",
        {".github/workflows/checks.yml": KIT_CHECKS.replace("uv sync --locked", "echo x").replace("uv run pytest", "echo y")
         .replace("      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0\n", "")
         + "      # - run: python3 bin/fwx test\n"})
control("a toy lefthook.yml", "lefthook.yml exists", {"lefthook.yml": "pre-commit:\n  commands: {}\n"})
control("a toy uv.toml", "uv.toml exists", {"uv.toml": 'exclude-newer = "3 days"\n'})
control("the kit's dependabot.yml", "uv ecosystem", {".github/dependabot.yml": KIT_DEPENDABOT})
control("a ci.yml that does not call checks.yml", "does not call checks.yml",
        {".github/workflows/ci.yml": "name: CI\njobs:\n  gitleaks:\n    runs-on: ubuntu-latest\n"})
control("no checks.yml", "checks.yml is missing", remove=(".github/workflows/checks.yml",))
control("an empty checks.yml", "no line that is not a comment", {".github/workflows/checks.yml": "# nothing\n"})
good = {".github/workflows/checks.yml": "# no uv here, and no `uv run`\n" + open(
    os.path.join(helpers.ROOT, ".github/workflows/checks.yml"), encoding="utf-8").read()}
d = helpers.mkdtemp("fwx-ci-c-")
shutil.copytree(os.path.join(toy, ".github"), os.path.join(d, ".github"))
helpers.write(d, ".github/workflows/checks.yml", good[".github/workflows/checks.yml"])
s.eq("a comment that says uv does not fail", problems(d), [])
s.done()
