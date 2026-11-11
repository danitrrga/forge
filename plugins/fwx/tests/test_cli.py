"""bin/fwx: a command is a file, the listing reads docstrings, a broken neighbour breaks nothing.

Runs a copy of bin/fwx and lib/fwx/ in a temp dir with three commands of its own: probe (returns the
exit code it is given), boom (raises when imported) and two_words (a dash on the command line).

Controls seen red, each on a copy of bin/fwx changed in one place:
  - a dispatcher that imports every command module before running the one asked for (the plan's control):
      FAIL: fwx probe: exit code: got 1, want 0
      FAIL: fwx probe: it ran with its arguments
      FAIL: fwx probe: no import error: got 'Traceback ... RuntimeError: boom was imported'
      (and the same for `fwx probe 3` and `fwx two-words`; 27 checks, 5 failed)
  - a listing that imports each module for its docstring instead of reading it with ast:
      FAIL: fwx help: exit code: got 1, want 0
      FAIL: fwx help: lists boom although it cannot be imported: usage: fwx <command> [args] ... RuntimeError: boom was imported
  - a dispatcher that turns the name into a path without checking it against the listing:
      FAIL: fwx ../commands/probe: unknown command exits 2: got 1, want 2
      FAIL: fwx _private: unknown command exits 2: got 1, want 2
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()
work = helpers.mkdtemp("fwx-cli-")
os.makedirs(os.path.join(work, "bin"))
shutil.copy(os.path.join(helpers.ROOT, "bin", "fwx"), os.path.join(work, "bin", "fwx"))
shutil.copytree(os.path.join(helpers.ROOT, "lib", "fwx"), os.path.join(work, "lib", "fwx"),
                ignore=shutil.ignore_patterns("__pycache__"))
commands = os.path.join(work, "lib", "fwx", "commands")
helpers.write(commands, "probe.py", '"""Answer, and exit with the code given."""\nimport sys\n\n\n'
              'def main(argv):\n    print("probe ran: " + " ".join(argv))\n    return int(argv[0]) if argv and argv[0].isdigit() else 0\n')
helpers.write(commands, "boom.py", '"""Fail as soon as it is imported."""\nraise RuntimeError("boom was imported")\n')
helpers.write(commands, "two_words.py", '"""Two words, one dash."""\n\n\ndef main(argv):\n    print("two-words ran")\n    return 0\n')
helpers.write(commands, "nodoc.py", "def main(argv):\n    return 0\n")
helpers.write(commands, "_private.py", '"""Not a command."""\n')


def run(*args):
    return subprocess.run([sys.executable, os.path.join(work, "bin", "fwx")] + list(args), cwd=work,
                          env=helpers.clean_env(), capture_output=True, text=True)


r = run("probe", "a", "b")
s.eq("fwx probe: exit code", r.returncode, 0)
s.ok("fwx probe: it ran with its arguments", "probe ran: a b" in r.stdout, r.stdout)
s.eq("fwx probe: no import error", r.stderr.strip(), "")
s.eq("fwx probe 3: the command's return value is the exit code", run("probe", "3").returncode, 3)
r = run("two-words")
s.ok("fwx two-words: file two_words.py runs as two-words", r.returncode == 0 and "two-words ran" in r.stdout, r.stderr)

for label, args in (("no argument", ()), ("help", ("help",))):
    r = run(*args)
    s.eq("fwx %s: exit code" % label, r.returncode, 0)
    s.ok("fwx %s: lists probe with its docstring line" % label,
         "probe" in r.stdout and "Answer, and exit with the code given." in r.stdout, r.stdout)
    s.ok("fwx %s: lists boom although it cannot be imported" % label,
         "boom" in r.stdout and "Fail as soon as it is imported." in r.stdout, r.stdout + r.stderr)
    s.ok("fwx %s: lists two-words, not two_words" % label, "two-words" in r.stdout and "two_words" not in r.stdout, r.stdout)
    s.ok("fwx %s: lists a command with no docstring" % label, "nodoc" in r.stdout, r.stdout)
    s.ok("fwx %s: does not list _private" % label, "_private" not in r.stdout, r.stdout)

for name in ("nosuch", "../commands/probe", "probe.py", "_private", "Probe"):
    r = run(name)
    s.eq("fwx %s: unknown command exits 2" % name, r.returncode, 2)
    s.ok("fwx %s: stderr names it and lists the commands" % name, "unknown command: " + name in r.stderr and "probe" in r.stderr, r.stderr)

s.done()
