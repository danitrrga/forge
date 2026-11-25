#!/usr/bin/env python3
"""One path writes the phase branch (3.4 U3): only lib/fwx/execute/integrate.py runs `git merge` or `git revert`, and nothing
in lib/fwx/ runs `git rebase` or `git reset --hard`. `git push` is lib/fwx/core/ci_gate.py's alone (09.6 T64: the end-of-part gate
pushes the phase branch so that CI can run on it; a push writes the remote, not the branch) and never forced: no `--force`, `-f`,
`--force-with-lease`, `--mirror` and no `+` refspec, in any module. The check reads the code (ast), not the behaviour.

The idea is marshal-factory's `merge-service.ts` and its ESLint rule (one module may merge); the check is ours.

What counts as running git: a call to `git`, `_git` or `out` (the helpers of execute/base.py and state.py) or to a function
that starts a list with "git" (`subprocess.run(["git", ...])`), with the forbidden word among its string arguments; and any
string that is a shell line holding `git [options] merge|revert|rebase|push` or `git reset --hard`. Docstrings and comments
are not code: they may name the commands to forbid them. `git merge-base` and `git merge --abort` of integrate.py are not
`merge`: the word must be the argument itself, and `merge --abort` is integrate.py's own.

Looking at nothing fails: the scan says how many files and git calls it read, and the real run must find integrate.py's own
`merge` and `revert` (zero would mean the scan sees no calls).

Seen red: before lib/fwx/execute/integrate.py existed the run stopped with `FileNotFoundError: ... lib/fwx/execute/integrate.py`
(the scan has no allowed path to look at). Controls: the planted modules below (one per forbidden command, plus a shell line)
must be named with their file and line, and docstrings and `merge-base` must not; each was seen failing on a copy of this file
with its own rule switched off, the first FAIL line of each:
  NEVER emptied:           FAIL: planted rebase: names the file and line: got [], want 'git rebase outside the allowed path: lib/fwx/zz_planted.py:5'
  ONLY_THERE emptied:      FAIL: planted merge in another module: names the file and line: got [], want 'git merge outside the allowed path: lib/fwx/zz_planted.py:5'
  shell strings off:       FAIL: planted a shell line: names the file and line: got [], want 'git rebase outside the allowed path: lib/fwx/zz_planted.py:5'
  reset --hard off:        FAIL: planted reset --hard: names the file and line: got [], want 'git reset --hard outside the allowed path: lib/fwx/zz_planted.py:5'
  GIT_CALLERS emptied:     FAIL: real lib: read some files (42) and some git calls (2): files 42, calls 2
"""
import ast
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

ROOT = helpers.ROOT
s = helpers.Suite()
ALLOWED = "lib/fwx/execute/integrate.py"
PUSHER = "lib/fwx/core/ci_gate.py"
ONLY_THERE = ("merge", "revert")  # words only ALLOWED may run
NEVER = ("rebase",)  # words no module may run
GIT_CALLERS = ("git", "_git", "out")
SHELL = re.compile(r"\bgit\s+(?:-\S+\s+(?:\S+\s+)?)*(merge|revert|rebase|push)\b|\bgit\s+(?:-\S+\s+)*reset\s+--hard\b")
SHELL_FORCE = re.compile(r"\bgit\b[^\n]*\bpush\b[^\n]*\s(--force\S*|--mirror|-[a-zA-Z]*f[a-zA-Z]*|\+\S+)")
FORCE_FLAG = re.compile(r"--force\S*|--mirror|-[a-zA-Z]*f[a-zA-Z]*|\+\S+")  # a push argument that overwrites the remote's branch


def _docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _strings(call):
    """The string constants of a call's arguments, list and tuple elements included."""
    out = []

    def walk(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
        elif isinstance(n, (ast.List, ast.Tuple)):
            for e in n.elts:
                walk(e)
    for a in call.args:
        walk(a)
    for k in call.keywords:
        walk(k.value)
    return out


def _is_git(call, strings):
    f = call.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    first_list = next((a for a in call.args if isinstance(a, (ast.List, ast.Tuple))), None)
    starts = bool(first_list and first_list.elts and isinstance(first_list.elts[0], ast.Constant) and first_list.elts[0].value == "git")
    return name in GIT_CALLERS or starts


def _forced(arg):
    """The hit word of a `git push` argument that overwrites the remote's branch, else None."""
    if not FORCE_FLAG.fullmatch(arg):
        return None
    return "push +refspec" if arg.startswith("+") else "push %s" % arg


def scan(root):
    """([(rule, rel path, line)], files read, git calls read) of the .py files under root/lib/fwx."""
    found, files, calls = [], 0, 0
    base = os.path.join(root, "lib", "fwx")
    for dirpath, _dirs, names in os.walk(base):
        for n in sorted(names):
            if not n.endswith(".py"):
                continue
            path = os.path.join(dirpath, n)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            files += 1
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            docs = _docstrings(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                    m = SHELL.search(node.value)
                    if m:
                        word = m.group(1) or "reset --hard"
                        if word in NEVER or word == "reset --hard" or rel != (PUSHER if word == "push" else ALLOWED):
                            found.append((word, rel, node.lineno))
                    m = SHELL_FORCE.search(node.value)
                    if m:
                        found.append((_forced(m.group(1)), rel, node.lineno))
                if not isinstance(node, ast.Call):
                    continue
                strings = _strings(node)
                if not _is_git(node, strings):
                    continue
                calls += 1
                pushing = "push" in [w.strip() for w in strings]
                for word in strings:
                    w = word.strip()
                    if w in NEVER or (w == "reset" and "--hard" in strings):
                        found.append(("rebase" if w == "rebase" else "reset --hard", rel, node.lineno))
                    elif w == "push" and rel != PUSHER:
                        found.append((w, rel, node.lineno))
                    elif w in ONLY_THERE and rel != ALLOWED:
                        found.append((w, rel, node.lineno))
                    elif pushing and _forced(w):
                        found.append((_forced(w), rel, node.lineno))
    return found, files, calls


def message(hit):
    word, rel, line = hit
    if word.startswith("push "):
        return "git %s is never allowed: %s:%d" % (word, rel, line)
    return "git %s outside the allowed path: %s:%d" % (word, rel, line)


def tree_with(module_text):
    """A copy of lib/ with one more module, `lib/fwx/zz_planted.py`."""
    dest = helpers.mkdtemp("fwx-writer-")
    shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(dest, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
    helpers.write(dest, "lib/fwx/zz_planted.py", module_text)
    return dest


PLANTED = [
    ("rebase", "from fwx.execute.base import git\n\n\ndef f(top):\n    return git(top, \"rebase\", \"phase\")\n", "git rebase outside the allowed path: lib/fwx/zz_planted.py:5"),
    ("push", "import subprocess\n\n\ndef f(top):\n    subprocess.run([\"git\", \"-C\", top, \"push\", \"origin\"])\n", "git push outside the allowed path: lib/fwx/zz_planted.py:5"),
    ("reset --hard", "from fwx.execute.base import git\n\n\ndef f(top):\n    git(top, \"reset\", \"--hard\", \"HEAD~1\")\n", "git reset --hard outside the allowed path: lib/fwx/zz_planted.py:5"),
    ("merge in another module", "from fwx.execute.base import git\n\n\ndef f(top, b):\n    git(top, \"merge\", \"--no-ff\", b)\n", "git merge outside the allowed path: lib/fwx/zz_planted.py:5"),
    ("revert in another module", "from fwx.execute.base import git\n\n\ndef f(top, c):\n    git(top, \"revert\", \"--no-edit\", c)\n", "git revert outside the allowed path: lib/fwx/zz_planted.py:5"),
    ("push --force", "from fwx.execute.base import git\n\n\ndef f(top):\n    git(top, \"push\", \"--force\", \"origin\")\n", "git push --force is never allowed: lib/fwx/zz_planted.py:5"),
    ("a shell line", "import os\n\n\ndef f():\n    os.system(\"git -C x rebase main\")\n", "git rebase outside the allowed path: lib/fwx/zz_planted.py:5"),
]
PUSH_LINES = [  # appended to the real ci_gate.py, the one module that may push: what it may not do even there
    ("push --force", 'def planted(top):\n    return _git(top, "push", "--force", "origin", "x")\n', "git push --force is never allowed"),
    ("push -f", 'def planted(top):\n    return _git(top, "push", "-f", "origin", "x")\n', "git push -f is never allowed"),
    ("push -fu", 'def planted(top):\n    return _git(top, "push", "-fu", "origin", "x")\n', "git push -fu is never allowed"),
    ("push --force-with-lease", 'def planted(top):\n    return _git(top, "push", "--force-with-lease", "origin", "x")\n', "git push --force-with-lease is never allowed"),
    ("push --mirror", 'def planted(top):\n    return _git(top, "push", "--mirror", "origin")\n', "git push --mirror is never allowed"),
    ("push of a + refspec", 'def planted(top):\n    return _git(top, "push", "origin", "+refs/heads/x:refs/heads/x")\n', "git push +refspec is never allowed"),
    ("a shell line with --force", 'def planted():\n    return "git -C x push --force origin x"\n', "git push --force is never allowed"),
    ("a shell line with a + refspec", 'def planted():\n    return "git push origin +x:x"\n', "git push +refspec is never allowed"),
]
INNOCENT = [
    ("docstrings and comments", '"""Never `git rebase`, `git push` or `git reset --hard`, and `git merge` is integrate.py\'s."""\n# git rebase here is a comment\n\n\ndef f():\n    """git push in a docstring"""\n    return 1\n'),
    ("merge-base and other words", "from fwx.execute.base import git\n\n\ndef f(top):\n    git(top, \"merge-base\", \"--is-ancestor\", \"a\", \"b\")\n    return {\"outcome\": \"merge\", \"x\": [\"push\"]}\n"),
]

if __name__ == "__main__":
    found, files, calls = scan(ROOT)
    s.ok("real lib: read some files (%d) and some git calls (%d)" % (files, calls), files > 5 and calls > 10, "files %d, calls %d" % (files, calls))
    s.eq("real lib: no git command outside its path", [message(h) for h in found], [])
    allowed_calls = 0
    with open(os.path.join(ROOT, ALLOWED), encoding="utf-8") as f:
        src = f.read()
    for word in ONLY_THERE:
        allowed_calls += len(re.findall(r'"%s"' % word, src))
    s.ok("real lib: integrate.py holds the merge and the revert the rule allows", allowed_calls >= 2, "found %d" % allowed_calls)
    for name, text, want in PLANTED:
        t = tree_with(text)
        got = [message(h) for h in scan(t)[0]]
        s.ok("planted %s: names the file and line" % name, want in got, "got %r, want %r" % (got, want))
    for name, text in INNOCENT:
        t = tree_with(text)
        got = [message(h) for h in scan(t)[0]]
        s.eq("not code, not git: %s" % name, got, [])
    # the allowed path may merge and revert, never rebase
    def appended(rel, text):
        """The messages for a copy of lib/ whose `rel` has `text` added at its end; None when `rel` is not there."""
        dest = helpers.mkdtemp("fwx-writer-")
        shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(dest, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
        p = os.path.join(dest, rel)
        if not os.path.exists(p):
            return None
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n\n" + text)
        return [message(h) for h in scan(dest)[0]]
    got = appended(ALLOWED, 'def planted(top):\n    return git(top, "rebase", "x")\n')
    s.ok("integrate.py may not rebase either", got is not None and any(g.startswith("git rebase outside the allowed path: lib/fwx/execute/integrate.py:") for g in got), repr(got))
    got = appended(ALLOWED, 'def planted(top):\n    return git(top, "push", "origin", "x")\n')
    s.ok("integrate.py may not push", got is not None and any(g.startswith("git push outside the allowed path: lib/fwx/execute/integrate.py:") for g in got), repr(got))
    got = appended(PUSHER, 'def planted(top):\n    return _git(top, "push", "origin", "x")\n')
    s.eq("a planted push in ci_gate.py is allowed", got, [])
    got = appended(PUSHER, 'def planted(top):\n    return _git(top, "rebase", "x")\n')
    s.ok("ci_gate.py may not rebase", got is not None and any(g.startswith("git rebase outside the allowed path: lib/fwx/core/ci_gate.py:") for g in got), repr(got))
    for name, text, want in PUSH_LINES:
        got = appended(PUSHER, text)
        s.ok("planted in ci_gate.py, %s: named with its file and line" % name,
             got is not None and any(g.startswith(want + ": lib/fwx/core/ci_gate.py:") for g in got), "got %r, want %r" % (got, want))
    s.ok("real lib: ci_gate.py holds the push the rule allows", os.path.exists(os.path.join(ROOT, PUSHER)) and
         '"push"' in open(os.path.join(ROOT, PUSHER), encoding="utf-8").read(), PUSHER)
    s.done()
