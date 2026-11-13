#!/usr/bin/env python3
"""The forge command grammar: `forge add` is `forge new`, `forge launch` is `forge start`, `forge check-public` is
`forge lint`. The other commands keep their names. An old name is removed, not aliased: it exits 2 with one line on
stderr naming the new one (`forge check-public: now 'forge lint'`), and runs nothing (no stdout, no side effect).
`forge --help` lists the new names and not the old.

What each new name does is checked where it always was, under the new name: tests/test_fresh_install.py (new),
tests/test_launch.py (start), tests/test_publish.py and plugins/fwx/tests/test_githooks.py (lint, and the three
githooks that call it).

Written first, run on master (the old names only): 18 FAIL lines, among them "help lists the new names: missing: got
['lint', 'new', 'start'], want []", "help still lists the old names: got ['add', 'check-public', 'launch'], want []",
"old name check-public --all: (exit, stdout, stderr): got (0, 'PASS check-public: 796 file(s) checked (...)', ''), want
(2, '', \"forge check-public: now 'forge lint'\\n\")" and "new name lint --help: exit: got 2, want 0". Negative control: with
the old-name table of forge/cli.py emptied the "old name" cases fail again as on master, and with `add` put back as a
subparser the help cases fail with "help still lists the old names: got ['add'], want []". The mutations are not kept.
"""
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures = []
RENAMED = {"add": "new", "launch": "start", "check-public": "lint"}
KEPT = ("sync", "skills", "doctor", "metrics", "test", "toolchain", "lock", "versions", "log", "session-start", "commit",
        "init", "uninstall")


def forge(tmp, *args):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, os.path.join(sandbox.FORGE, "bin", "forge")] + list(args), cwd=tmp, env=env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout, r.stderr


def want(label, got, expected):
    if got != expected:
        failures.append("%s: got %r, want %r" % (label, got, expected))


def main():
    with tempfile.TemporaryDirectory(prefix="forge-grammar-") as tmp:
        code, out, err = forge(tmp, "--help")
        want("forge --help: exit", code, 0)
        names = set(re.findall(r"^    ([a-z][a-z-]*)\s", out, re.M))
        want("help lists the new names: missing", sorted(set(RENAMED.values()) - names), [])
        want("help lists the kept names: missing", sorted(set(KEPT) - names), [])
        want("help still lists the old names", sorted(names & set(RENAMED)), [])
        want("help usage line still lists the old names", sorted(set(RENAMED) & set(re.findall(r"[a-z][a-z-]*", out.split("\n\n")[0]))), [])
        for old, new in RENAMED.items():
            for extra in ([], ["--all"], ["some-arg", "--name", "x"]):
                code, out, err = forge(tmp, old, *extra)
                want("old name %s %s: (exit, stdout, stderr)" % (old, " ".join(extra)), (code, out, err),
                     (2, "", "forge %s: now 'forge %s'\n" % (old, new)))
            code, out, err = forge(tmp, new, "--help")
            want("new name %s --help: exit" % new, code, 0)
            want("new name %s --help: says its own name" % new, "forge %s" % new in out or " %s " % new in out, True)
        # the old name is refused before anything runs, also where the new one would refuse for a missing world
        code, out, err = forge(tmp, "add", os.path.join(tmp, "nowhere"))
        want("old add with a path that is not a directory: it never gets to say so", "directory" in out + err, False)
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: command grammar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
