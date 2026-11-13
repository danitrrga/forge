"""bin/fwx: the table routes, the listing reads the table, a broken neighbour breaks nothing.

Runs a copy of bin/fwx and lib/fwx/ in a temp dir with its own routes.py and four commands of its own: probe (returns the exit code
it is given), boom (raises when imported), two-words (`fwx two-words`, a dash on the command line) and `thing new` (an object and a
verb). tests/test_commands_table.py holds the real table; this file is about the dispatcher.

Controls seen red, each on a copy of bin/fwx changed in one place:
  - a dispatcher that imports every command module of the table before running the one asked for (6 failed):
      FAIL: fwx probe: exit code: got 1, want 0
      FAIL: fwx probe: it ran with its arguments
      FAIL: fwx probe: no import error: got 'Traceback (most recent call last): ... RuntimeError: boom was imported'
  - a listing that imports each module of the table instead of reading it (22 failed):
      FAIL: fwx no argument: exit code: got 1, want 0
      FAIL: fwx no argument: lists boom although it cannot be imported: usage: fwx <object> [<verb>] [args] ...
  - a dispatcher that imports the module named on the command line without asking the table (13 failed):
      FAIL: fwx thing new x: the handler's own words come first: thing ran: new x
      FAIL: fwx nosuch: unknown command exits 2: got 1, want 2
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
                ignore=shutil.ignore_patterns("__pycache__", "test.py"))
commands = os.path.join(work, "lib", "fwx", "commands")
for f in os.listdir(commands):  # the toy world has only the commands of its own table
    if f.endswith(".py") and f != "__init__.py":
        os.remove(os.path.join(commands, f))
helpers.write(commands, "probe.py", '"""Answer, and exit with the code given."""\nimport sys\n\n\n'
              'def main(argv):\n    print("probe ran: " + " ".join(argv))\n    return int(argv[0]) if argv and argv[0].isdigit() else 0\n')
helpers.write(commands, "boom.py", '"""Fail as soon as it is imported."""\nraise RuntimeError("boom was imported")\n')
helpers.write(commands, "two_words.py", '"""Two words, one dash."""\n\n\ndef main(argv):\n    print("two-words ran")\n    return 0\n')
helpers.write(commands, "thing.py", '"""An object with a verb."""\n\n\ndef main(argv):\n    print("thing ran: " + " ".join(argv))\n    return 0\n')
helpers.write(commands, "_private.py", '"""Not a command."""\n')
# The toy table: the same functions bin/fwx calls on the real one (table, objects, refusal, route), with four rows of its own.
helpers.write(os.path.join(work, "lib", "fwx"), "routes.py", """ROWS = [
    ("probe", None, "probe", [], "answer, and exit with the code given"),
    ("boom", None, "boom", [], "fail as soon as it is imported"),
    ("two-words", None, "two_words", [], "two words, one dash"),
    ("thing new", "thing make", "thing", ["make"], "an object with a verb"),
]


def table():
    new = {tuple(r[0].split()): r for r in ROWS}
    return new, {tuple(r[1].split()): r[0] for r in ROWS if r[1]}


def objects():
    out = {}
    for r in ROWS:
        out.setdefault(r[0].split()[0], []).append(r)
    return out


def refusal(argv):
    return None


def route(argv):
    new, _ = table()
    obj, rest = argv[0], list(argv[1:])
    if (obj,) in new:
        return new[(obj,)][2], new[(obj,)][3] + rest
    if rest and (obj, rest[0]) in new:
        return new[(obj, rest[0])][2], new[(obj, rest[0])][3] + rest[1:]
    return ("verb?", obj) if any(len(k) > 1 and k[0] == obj for k in new) else None
""")


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
r = run("thing", "new", "x")
s.ok("fwx thing new x: the handler's own words come first", r.returncode == 0 and "thing ran: make x" in r.stdout, r.stdout + r.stderr)

for label, args in (("no argument", ()), ("help", ("help",))):
    r = run(*args)
    s.eq("fwx %s: exit code" % label, r.returncode, 0)
    s.ok("fwx %s: lists probe with its help line" % label,
         "fwx probe" in r.stdout and "answer, and exit with the code given" in r.stdout, r.stdout)
    s.ok("fwx %s: lists boom although it cannot be imported" % label,
         "fwx boom" in r.stdout and "fail as soon as it is imported" in r.stdout, r.stdout + r.stderr)
    s.ok("fwx %s: lists two-words, not two_words" % label, "fwx two-words" in r.stdout and "two_words" not in r.stdout, r.stdout)
    s.ok("fwx %s: lists the verb of an object" % label, "fwx thing new" in r.stdout, r.stdout)
    s.ok("fwx %s: does not list _private" % label, "_private" not in r.stdout, r.stdout)

for name in ("nosuch", "../commands/probe", "probe.py", "_private", "Probe", "two_words"):
    r = run(name)
    s.eq("fwx %s: unknown command exits 2" % name, r.returncode, 2)
    s.ok("fwx %s: stderr names it and lists the commands" % name, "unknown command: " + name in r.stderr and "fwx probe" in r.stderr, r.stderr)

s.done()
