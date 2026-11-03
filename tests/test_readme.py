#!/usr/bin/env python3
"""README.md against the code it describes.

copied-from: forge tests/test_readme.py @582258b, adapted (fwx's own subcommands, paths and constants; the
checks work on any repo root, so the controls run on copies of this one)

Checked, for the real README and for edited copies in a toy repo:
  - every subcommand the README names (`fwx <name>` in backticks or in the first code block) is one `bin/fwx help`
    lists, and the code block names every one of them (`help` is built in, the rest are the files of
    lib/fwx/commands/);
  - every path in backticks that starts with a repo prefix exists (a placeholder such as <name> or * cuts it
    there: the directory before it must exist);
  - every UPPER_CASE name in backticks is assigned in a .py of lib/ or bin/, or read by a script of githooks/
    (an environment variable the hooks take, which no Python assigns);
  - reading zero paths or zero constants is a failure.

Why: "documentation carries no figures or lists copied from the code: it points at the constant, the file or the
command that gives them". Without a check that compares, it broke every round.

Controls (each is the real README with one change, in a toy copy of the repo, and must fail its own check):
  - an invented subcommand
  - a subcommand missing from the block
  - a command file added to the code and not to the README
  - a dead path
  - a constant that does not exist
  - a README with no path
  - a README with no constant
Seen red, each on a copy of this test with one check switched off (`if <check>:` made `if False:`), 12 checks each:
  - subcommands named but not in the code:
      FAIL: control an invented subcommand: fails with 'named but not in the code': problems: []
      FAIL: control an invented subcommand in prose: fails with 'named but not in the code': problems: []
  - subcommands missing from the block:
      FAIL: control a subcommand missing from the block: fails with "missing from the README's code block": problems: []
      FAIL: control a command added to the code only: fails with 'extra': problems: []
  - dead paths:
      FAIL: control a dead path: fails with 'paths named and missing': problems: []
  - unknown constants:
      FAIL: control a constant that does not exist: fails with 'never assigned': problems: []
  - zero paths, zero constants:
      FAIL: control a README with no path: fails with 'read zero paths': problems: []
      FAIL: control a README with no constant: fails with 'read zero constants': problems: []
  - prose commands not read (backticked `fwx <name>` ignored):
      FAIL: control an invented subcommand in prose: fails with 'named but not in the code': problems: []
  - the command list hard-coded instead of read from `bin/fwx help`:
      FAIL: control a command added to the code only: fails with 'extra': problems: []
The README's own mention of the command `bin/fwx statusline` (it does not exist yet) was removed from the README;
with the sentence put back the check says: subcommands named but not in the code: ['statusline']. A first version
of named_paths skipped every path with a placeholder and the real README then read zero paths:
  FAIL: the real README against the code: got ['read zero paths'], want []
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

PREFIXES = ("bin/", "lib/", "tests/", "githooks/", "scripts/", ".github/", ".claude-plugin/")
BUILTIN = {"help"}
NOT_COPIED = shutil.ignore_patterns("__pycache__", ".git", ".claude")


def commands(root):
    """The subcommands the code at `root` has: what its own `bin/fwx help` lists, plus the built-in help."""
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "help"], capture_output=True, text=True,
                       env=helpers.clean_env(PYTHONDONTWRITEBYTECODE="1"))
    listed = set(re.findall(r"^  (\S+)  ", r.stdout, re.M))
    return listed | BUILTIN if r.returncode == 0 else set()


def use_block(text):
    m = re.search(r"^## Use\n+```\n(.*?)\n```", text, re.S | re.M)
    return set(re.findall(r"\bbin/fwx ([a-z][a-z0-9-]*)", m.group(1))) if m else set()


def named_commands(text):
    """What the README says to run: the code block, and any backticked `fwx <name>` or `bin/fwx <name>`."""
    out = use_block(text)
    for tok in re.findall(r"`([^`\n]+)`", text):
        m = re.match(r"(?:python3 )?(?:bin/)?fwx ([a-z][a-z0-9-]*)\b", tok)
        if m:
            out.add(m.group(1))
    return out


def named_paths(text):
    out = set()
    for tok in re.findall(r"`([^`\s]+)`", text):
        tok = tok.rstrip(".,:;)")
        if tok.startswith(PREFIXES):
            out.add(re.split(r"[<*]", tok)[0])  # `lib/fwx/commands/<name>.py` names the directory it is in
    return out


def named_constants(text):
    return set(re.findall(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]+)`", text))


def source(root, tops, suffix=None):
    chunks = []
    for top in tops:
        for d, _, files in os.walk(os.path.join(root, top)):
            for f in files:
                if suffix is None or f.endswith(suffix) or (top == "bin" and f == "fwx"):
                    with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                        chunks.append(fh.read())
    return "\n".join(chunks)


def known(const, py, hooks):
    return bool(re.search(r"^\s*%s\s*=" % re.escape(const), py, re.M)
                or re.search(r"\$\{?%s\b" % re.escape(const), hooks))


def problems(root, readme):
    """The failures of `readme` against the code at `root`, as strings; no failure is an empty list."""
    have = commands(root)
    named, block = named_commands(readme), use_block(readme)
    paths, consts = named_paths(readme), named_constants(readme)
    py, hooks = source(root, ("lib", "bin"), ".py"), source(root, ("githooks",))
    out = []
    if len(have) <= len(BUILTIN):
        out.append("read no subcommand from the code: bin/fwx help listed %r" % sorted(have))
    if named - have:
        out.append("subcommands named but not in the code: %s" % sorted(named - have))
    if have - block:
        out.append("subcommands missing from the README's code block: %s" % sorted(have - block))
    dead = sorted(p for p in paths if not os.path.exists(os.path.join(root, p.rstrip("/"))))
    if dead:
        out.append("paths named and missing: %s" % dead)
    unknown = sorted(c for c in consts if not known(c, py, hooks))
    if unknown:
        out.append("constants named and never assigned: %s" % unknown)
    if not paths:
        out.append("read zero paths")
    if not consts:
        out.append("read zero constants")
    return out


s = helpers.Suite()
real = open(os.path.join(helpers.ROOT, "README.md"), encoding="utf-8").read()
s.eq("the real README against the code", problems(helpers.ROOT, real), [])
s.ok("the real README names paths, constants and commands",
     len(named_paths(real)) > 0 and len(named_constants(real)) > 0 and len(named_commands(real)) > 1,
     "%d paths, %d constants, %d commands" % (len(named_paths(real)), len(named_constants(real)),
                                              len(named_commands(real))))

toy = helpers.mkdtemp("fwx-readme-")
for top in ("bin", "lib", "githooks"):
    shutil.copytree(os.path.join(helpers.ROOT, top), os.path.join(toy, top), ignore=NOT_COPIED)
s.eq("the README against a copy of the code", problems(toy, real), [])


def control(name, text, needle):
    got = problems(toy, text)
    s.ok("control %s: fails with %r" % (name, needle), any(needle in g for g in got), "problems: %r" % got)


block_line = re.search(r"^python3 bin/fwx help.*\n", real, re.M).group(0)
control("an invented subcommand", real.replace(block_line, block_line + "python3 bin/fwx teleport\n", 1),
        "named but not in the code")
control("a subcommand missing from the block", real.replace(block_line, "", 1), "missing from the README's code block")
control("an invented subcommand in prose", real + "\nRun `fwx statusline` first.\n", "named but not in the code")
control("a dead path", real + "\nSee `lib/fwx/no_such_module.py`.\n", "paths named and missing")
control("a constant that does not exist", real + "\nSet `NO_SUCH_TABLE`.\n", "never assigned")
control("a README with no path", re.sub(r"`[^`\s]*/[^`\s]*`", "`x`", real), "read zero paths")
control("a README with no constant", real.replace("`FORGE_ROOT`", "`forge checkout`"), "read zero constants")

helpers.write(toy, "lib/fwx/commands/extra.py", '"""A command the README does not know."""\n\n\ndef main(argv):\n    return 0\n')
control("a command added to the code only", real, "extra")
os.remove(os.path.join(toy, "lib", "fwx", "commands", "extra.py"))
s.eq("the README against the code again, the command gone", problems(toy, real), [])
s.done()
