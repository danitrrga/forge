#!/usr/bin/env python3
"""No module of lib/fwx finds fwx's state folder (`<git common dir>/fwx`) itself (DTC-64).

`config.fwx_dir(cwd)` is the one owner: it is the workspace's git dir when the repository is nested in a workspace, so a module that
asks git for `--git-common-dir` on its own puts runs, briefs, sessions and the gate lock in the nested repo, where nothing else
looks. Four modules ask git for that on purpose (ALLOWED); every other one is a defect, and a new module cannot bring the class
back one file at a time.

Seen red on lib/fwx as of the phase's T1 (config.fwx_dir existed, nothing called it):
  FAIL: modules that find fwx's folder themselves: commands/walk.py, commands/wave.py, core/verify.py, execute/integrate.py, execute/prepare.py, execute/review.py, execute/run.py, state.py
Controls: `X = "--git-common-dir"` appended to lib/fwx/commands/stage.py made the run print
  FAIL: modules that find fwx's folder themselves: commands/stage.py
(the class, not the eight); the toy-lib cases below prove, on every run, that a code string is found, a docstring is not, an allowed
module is skipped, and a scan of an empty lib reads zero modules.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

LIB = os.path.join(helpers.ROOT, "lib", "fwx")
FLAG = "--git-common-dir"
ALLOWED = {
    "config.py": "the owner of fwx_dir",
    "execute/base.py": "`linked`: whether a folder is a linked worktree of its own repository",
    "execute/orca.py": "the worker's own git dir and its exclude file",
    "commands/migrate_gsd.py": "the repository being migrated",
}

s = helpers.Suite()


def modules(lib):
    for dirpath, dirs, files in os.walk(lib):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def passes_flag(path):
    """Whether the module has a string that carries the flag, in code: a docstring may name it."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and FLAG in n.value and id(n) not in docs
               for n in ast.walk(tree))


def offenders(lib, allowed):
    """(modules read, relative paths of the modules outside `allowed` that pass the flag)."""
    read, bad = 0, []
    for path in sorted(modules(lib)):
        read += 1
        rel = os.path.relpath(path, lib).replace(os.sep, "/")
        if rel not in allowed and passes_flag(path):
            bad.append(rel)
    return read, bad


read, bad = offenders(LIB, ALLOWED)
s.ok("the scan read the modules of lib/fwx (read %d)" % read, read > 40)
s.ok("modules that find fwx's folder themselves", not bad, ", ".join(bad))
for name in ALLOWED:
    s.ok("allowed module %s exists and passes the flag (else its row is stale)" % name,
         os.path.isfile(os.path.join(LIB, name)) and passes_flag(os.path.join(LIB, name)))

# negative controls, on a toy lib, so the check is seen to fail without touching the real one
toy = helpers.mkdtemp("fwx-dir-")
helpers.write(toy, "ok.py", '"""Names `--git-common-dir` in prose only."""\nX = 1\n')
helpers.write(toy, "sub/bad.py", 'ARGS = ["rev-parse", "--git-common-dir"]\n')
r, b = offenders(toy, {})
s.eq("control: a string in code carrying the flag is found, a docstring is not", (r, b), (2, ["sub/bad.py"]))
s.eq("control: an allowed module is skipped", offenders(toy, {"sub/bad.py": "x"})[1], [])
empty = helpers.mkdtemp("fwx-dir-empty-")
s.eq("control: an empty lib reads zero modules (the test above would fail on it)", offenders(empty, {})[0], 0)

s.done()
