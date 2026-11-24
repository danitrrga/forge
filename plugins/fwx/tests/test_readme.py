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
  - reading zero paths or zero constants is a failure;
  - `## Configuration` names every key of `DEFAULTS` (read from the `lib/fwx/config.py` of the repo under test) and every key
    of its `project` table, each as a backticked name (`key`, `key.sub` or `parent.key`), and carries the phrases that say how
    a key is changed: `ask an agent`, `fixed core` (what is not configurable) and `Linux` (the one platform). A section that
    lists the keys and says nothing about changing them fails.

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
  - the Configuration section without `walk`, without `project.check_timeout_s`, without each of the three phrases
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
import importlib.util
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
    """The commands the code at `root` has, as word tuples: what its own `bin/fwx help` lists (`fwx phase new` is ("phase", "new")),
    plus the built-in help."""
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "fwx"), "help"], capture_output=True, text=True,
                       env=helpers.clean_env(PYTHONDONTWRITEBYTECODE="1"))
    listed = {tuple(m.split()) for m in re.findall(r"^  fwx ([a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*)(?: --[a-z]+)?  ", r.stdout, re.M)}
    return listed | {(b,) for b in BUILTIN} if r.returncode == 0 else set()


WORDS = r"([a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*)"


def use_block(text):
    """The commands of the `## Use` code block, as word tuples: the words after `bin/fwx` up to the first flag or placeholder."""
    m = re.search(r"^## Use\n+```\n(.*?)\n```", text, re.S | re.M)
    return {tuple(w.split()) for w in re.findall(r"\bbin/fwx " + WORDS, m.group(1))} if m else set()


def named_commands(text):
    """What the README says to run: the code block, and any backticked `fwx <words>` or `bin/fwx <words>`."""
    out = use_block(text)
    for tok in re.findall(r"`([^`\n]+)`", text):
        m = re.match(r"(?:python3 )?(?:bin/)?fwx " + WORDS, tok)
        if m:
            out.add(tuple(m.group(1).split()))
    return out


def exists(name, have):
    """A named command exists when a listed command is the start of it (`migrate-gsd plan` starts with `migrate-gsd`)."""
    return any(name[:len(h)] == h for h in have)


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


PHRASES = ("ask an agent", "fixed core", "Linux")


def config_section(text):
    m = re.search(r"^## Configuration\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def config_keys(root):
    """`(DEFAULTS' keys, DEFAULTS["project"]'s keys)` of the lib/fwx/config.py of the repo at `root`."""
    spec = importlib.util.spec_from_file_location("fwx_config_of_" + str(abs(hash(root))), os.path.join(root, "lib", "fwx", "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.DEFAULTS), list(mod.DEFAULTS["project"])


def config_tokens(section):
    return re.findall(r"`([^`\n]+)`", section)


def config_problems(root, readme):
    """`(top keys not named, project keys not named, phrases missing)` of the `## Configuration` section of `readme`. A top key is
    named by `key` or `key.sub`, a project key by `key` or `project.key`."""
    section = config_section(readme)
    top, project = config_keys(root)
    toks = config_tokens(section)
    return ([k for k in top if not any(t == k or t.startswith(k + ".") for t in toks)],
            [k for k in project if not any(t in (k, "project." + k) for t in toks)],
            [p for p in PHRASES if p not in section])


def problems(root, readme):
    """The failures of `readme` against the code at `root`, as strings; no failure is an empty list."""
    have = commands(root)
    named, block = named_commands(readme), use_block(readme)
    paths, consts = named_paths(readme), named_constants(readme)
    py, hooks = source(root, ("lib", "bin"), ".py"), source(root, ("githooks",))
    out = []
    if len(have) <= len(BUILTIN):
        out.append("read no subcommand from the code: bin/fwx help listed %r" % sorted(have))
    missing = sorted(" ".join(n) for n in named if not exists(n, have))
    if missing:
        out.append("subcommands named but not in the code: %s" % missing)
    unblocked = sorted({h[0] for h in have} - {b[0] for b in block})
    if unblocked:
        out.append("subcommands missing from the README's code block: %s" % unblocked)
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
control("an invented subcommand in prose", real + "\nRun `fwx teleport` first.\n", "named but not in the code")
control("a dead path", real + "\nSee `lib/fwx/no_such_module.py`.\n", "paths named and missing")
control("a constant that does not exist", real + "\nSet `NO_SUCH_TABLE`.\n", "never assigned")
control("a README with no path", re.sub(r"`[^`\s]*/[^`\s]*`", "`x`", real), "read zero paths")
control("a README with no constant", real.replace("`FORGE_ROOT`", "`forge checkout`"), "read zero constants")

routes = os.path.join(toy, "lib", "fwx", "routes.py")
with open(routes, encoding="utf-8") as fh:
    routes_text = fh.read()
with open(routes, "w", encoding="utf-8") as fh:
    fh.write(routes_text.replace("ROWS = [\n", 'ROWS = [\n    ("extra", None, "extra", [], "A command the README does not know"),\n', 1))
control("a command added to the table only", real, "extra")
with open(routes, "w", encoding="utf-8") as fh:
    fh.write(routes_text)
s.eq("the README against the code again, the command gone", problems(toy, real), [])

def config_check(label, miss, what):
    """One line each, so a failure reads `FAIL: <label> -> missing a, b`."""
    s.ok(label + (" -> missing " + ", ".join(miss) if miss else ""), not miss)
    return what


top_keys, project_keys = config_keys(toy)
s.ok("DEFAULTS has keys to name", len(top_keys) > 5 and len(project_keys) > 5, "%d top, %d project" % (len(top_keys), len(project_keys)))
top_miss, project_miss, phrase_miss = config_problems(toy, real)
config_check("## Configuration names every key of DEFAULTS", top_miss, None)
config_check("## Configuration names every key of its project", project_miss, None)
config_check("## Configuration says how to change a key", phrase_miss, None)


def config_false_readback(readme):
    """What `## Configuration` names as the command that reads a changed key back, when `fwx session --json` prints no config value
    (it shows the stage, the branch and the paths, never rounds, limits, weekly, factory, integrations, paths, linear or checks)."""
    return [c for c in ("fwx session --json",) if c in config_section(readme)]


bad_readback = config_false_readback(real)
s.ok("## Configuration names no command that does not read a key back" + (" -> " + ", ".join(bad_readback) if bad_readback else ""), not bad_readback)
s.ok("control a section that sends the agent to `fwx session --json`: fails", config_false_readback(real.replace("### What is not configurable", "Run `fwx session --json`.\n\n### What is not configurable", 1)) == ["fwx session --json"])


def config_control(name, text, which, needle):
    got = config_problems(toy, text)[which]
    s.ok("control %s: fails naming %r" % (name, needle), needle in got, "missing: %r" % got)


config_control("without walk", re.sub(r"`walk[.`][^`]*`?", "`x`", real), 0, "walk")
config_control("without project.check_timeout_s", re.sub(r"`(project\.)?check_timeout_s`", "`x`", real), 1, "check_timeout_s")
for phrase in PHRASES:
    config_control("without %r" % phrase, real.replace(phrase, "x"), 2, phrase)
s.done()
