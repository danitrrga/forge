"""bin/fwx: a command is a file, the listing reads docstrings, a broken neighbour breaks nothing; a command can also
be written verb first (`fwx <verb> <noun>`), through a row of lib/fwx/names.py or a file commands/<verb>_<noun>.py.

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

Verb-first dispatch, seen red:
  - on the untouched base (no lib/fwx/names.py; 28 checks, the run stops there):
      FAIL: lib/fwx/names.py: the table imports: cannot import name 'names' from 'fwx' (.../lib/fwx/__init__.py)
  - with the table and the untouched bin/fwx (the plan's control: `fwx find phase` exits 2; 187 checks, 85 failed):
      FAIL: fwx greet world: runs commands/greet_world.py with the rest: fwx: unknown command: greet
      FAIL: fwx find nosuch: stderr names it and lists the commands: fwx: unknown command: find
      FAIL: state resolve / find phase: same exit code: got 2, want 0
      FAIL: state resolve / find phase: same stdout: got '', want 'phase_dir: .../.fwx/milestones/v1/phases/01-alpha\n...'
      FAIL: model / show model: same exit code: got 2, want 0
      FAIL: statusline / show statusline: same stdout and exit code: old '' exit 0, new '' exit 2
  - a dispatcher that ignores the second word (it takes the first row whose verb matches):
      FAIL: state list / list phases: same exit code: got 2, want 0
      FAIL: state list / list phases: same stdout: got '', want '{\n  "plan_root": ...'
      FAIL: model / show model: same stdout: got '', want 'opus\n'
      (7 failed)
  - the table checks each have a planted defect in a copy of the table (the "control," lines), caught with its message.

The table's proposed names are the owner's to confirm: this test reads every name from lib/fwx/names.py and spells none,
and spells only commands of today. Set FWX_TIMING=1 for the median-of-10 timing of the verb-first statusline (under 100 ms;
49 ms measured).
"""
import os
import re
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

# ---- verb first: `fwx <verb> <noun>` --------------------------------------------------------------------------------------
sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
try:
    from fwx import names  # noqa: E402
except ImportError as e:
    s.ok("lib/fwx/names.py: the table imports", False, str(e))
    s.done()


def new_of(old):
    """The verb-first name the table gives to a command of today, as words."""
    found = [n for n, o in names.ROWS if o == old]
    s.eq("the table has one row for %r" % old, len(found), 1)
    return found[0].split() if found else ["no-row-for"] + old.split()


# a file commands/<verb>_<noun>.py runs as `fwx <verb> <noun>`, and a command of its own is never looked up in the table
helpers.write(commands, "greet_world.py", '"""Greet."""\n\n\ndef main(argv):\n    print("greet ran: " + " ".join(argv))\n'
              '    return int(argv[0]) if argv and argv[0].isdigit() else 0\n')
r = run("greet", "world", "a", "b")
s.ok("fwx greet world: runs commands/greet_world.py with the rest", r.returncode == 0 and "greet ran: a b" in r.stdout, (r.stdout + r.stderr)[:200])
s.eq("fwx greet world 3: the exit code is the command's", run("greet", "world", "3").returncode, 3)
r = run("probe", "greet", "world")
s.ok("fwx probe greet world: a command of its own keeps its arguments", r.returncode == 0 and "probe ran: greet world" in r.stdout,
     (r.stdout + r.stderr)[:200])
r = run(*new_of("statusline"))
s.ok("fwx %s: runs the statusline although boom.py cannot be imported" % " ".join(new_of("statusline")),
     r.returncode == 0 and r.stderr.strip() == "", "exit %d: %s" % (r.returncode, r.stderr[-300:]))

# a name with no row, and a verb alone, exit 2 naming what was asked and listing the commands
for args in (("find", "nosuch"), ("nosuch", "phase"), ("find",), ("greet", "nobody")):
    r = run(*args)
    s.eq("fwx %s: exit code" % " ".join(args), r.returncode, 2)
    s.ok("fwx %s: stderr names it and lists the commands" % " ".join(args),
         "unknown command: %s\n" % " ".join(args[:2]) in r.stderr and "commands:" in r.stderr, r.stderr[:200])

# the listing keeps its command rows and adds the verbs, in lines a reader of the rows would not take for a command
r = run("help")
rows = set(re.findall(r"^  (\S+)  ", r.stdout, re.M))
s.ok("fwx help: the command rows are still there", {"probe", "state", "wave"} <= rows, r.stdout)
s.eq("fwx help: no verb is read as a command row", sorted(rows & set(names.verbs())), [])
for verb, nouns in names.verbs().items():
    s.ok("fwx help: the verb %r lists its nouns" % verb, "  %s: %s\n" % (verb, ", ".join(nouns)) in r.stdout, r.stdout[-400:])
s.ok("fwx help: names the file that says what each verb reaches", "lib/fwx/names.py" in r.stdout, r.stdout[-300:])

# ---- the same bytes: each spelling of a command of today gives the same output and the same exit code ----------------------
repo = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
env = {"HOME": helpers.mkdtemp("fwx-cli-home-"), "CLAUDE_CODE_SESSION_ID": "sess-eq", "LINEAR_API_KEY": ""}


def go(words, *args, input=""):
    return helpers.fwx(repo, *(list(words) + list(args)), input=input, env=env)


s.eq("setup: a phase in the toy repo", go(["state"], "new-phase", "alpha").returncode, 0)
sha = helpers.git(repo, "rev-parse", "HEAD").strip()
for old, args in (("state resolve", []), ("state list", ["--json"]), ("model", ["planner", "small"]),
                  ("discuss start", ["--json"]), ("wave check-base", [sha]), ("plan check", [os.path.join(repo, "nowhere")])):
    a, b = go(old.split(), *args), go(new_of(old), *args)
    label = "%s / %s" % (old, " ".join(new_of(old)))
    s.eq("%s: same exit code" % label, b.returncode, a.returncode)
    s.eq("%s: same stdout" % label, b.stdout, a.stdout)
    s.ok("%s: the new spelling is known" % label, "unknown command" not in b.stderr, b.stderr[:200])
    if old not in ("plan check", "wave check-base"):  # these two answer on stderr and in the exit code only
        s.ok("%s: there is output to compare" % label, a.stdout.strip() != "", "exit %d, stderr %r" % (a.returncode, a.stderr[:200]))

# every row, with an argument no command takes: a usage error or a refusal, no side effect, the same in both spellings
swept = 0
before = sorted(os.listdir(repo))
for new, old in names.ROWS:
    a, b = go(old.split(), "--no-such-flag"), go(new.split(), "--no-such-flag")
    swept += 1
    s.ok("%s / %s: same stdout and exit code" % (old, new), (a.stdout, a.returncode) == (b.stdout, b.returncode),
         "old %r exit %d, new %r exit %d" % (a.stdout[:80], a.returncode, b.stdout[:80], b.returncode))
    s.ok("%s: the new name reaches the command" % new, "unknown command" not in b.stderr and "Traceback" not in b.stderr, b.stderr[:200])
s.ok("the sweep looked at every row of the table (%d)" % swept, swept == len(names.ROWS) and swept > 0)
s.eq("the sweep wrote nothing in the toy repo", sorted(os.listdir(repo)), before)

# ---- the table is complete: every command and subcommand the CLI has is a row, and every row is a command -----------------
nogit = helpers.mkdtemp("fwx-cli-nogit-")


def registry():
    """(listed, found) read from the CLI itself: the commands its listing shows, and for each the subcommands its --help
    names (`fwx <cmd> [--project NAME] <sub>`, `<a|b|c>` and argparse's indented `sub  help` lines). found holds 'cmd' for a
    command with no subcommand and 'cmd sub' for each of the others."""
    out = helpers.fwx(nogit, "help").stdout
    block = out.split("commands:\n", 1)[1].split("\n\n", 1)[0]
    listed = re.findall(r"^  (\S+)  ", block, re.M)
    found = set()
    for cmd in listed:
        r = helpers.fwx(nogit, cmd, "--help", input="")
        text = r.stdout + r.stderr
        subs = set()
        for m in re.finditer(r"\bfwx %s (?:\[--project NAME\] )?(?:<([a-z-]+(?:\|[a-z-]+)+)>|([a-z][a-z-]*)\b)" % re.escape(cmd), text):
            subs |= set(m.group(1).split("|")) if m.group(1) else {m.group(2)}
        subs |= set(re.findall(r"^    ([a-z][a-z-]*)\s{2,}\S", text, re.M))
        found |= {cmd + " " + x for x in subs} if subs else {cmd}
    return listed, found


def problems(rows, unchanged, gone, found, listed):
    """What is wrong with a copy of the table against what the CLI has."""
    out = []
    covered = [old for _, old in rows] + list(unchanged) + list(gone)
    out += ["no row for the command: %s" % c for c in sorted(found - set(covered))]
    out += ["a row names a command that does not exist: %s" % c for c in sorted(set(covered) - found)]
    seen = {}
    for new, _ in rows:
        seen[new] = seen.get(new, 0) + 1
    out += ["two rows give the new name %r" % n for n, k in sorted(seen.items()) if k > 1]
    out += ["the new name %r is not a verb and a noun" % n for n, _ in rows if not re.fullmatch(r"[a-z]+ [a-z]+", n)]
    out += ["the verb of %r is a command of today and would never be looked up" % n for n, _ in rows if n.split()[0] in listed]
    return out


listed, found = registry()
on_disk = sorted(f[:-3].replace("_", "-") for f in os.listdir(os.path.join(helpers.ROOT, "lib", "fwx", "commands"))
                 if f.endswith(".py") and not f.startswith("_"))
s.eq("the listing shows every command file", sorted(listed), on_disk)
s.ok("the registry looked at %d commands and %d names" % (len(listed), len(found)), len(listed) > 0 and len(found) >= len(listed))
s.eq("the table against the CLI: no problem", problems(names.ROWS, names.UNCHANGED, names.GONE, found, listed), [])

# negative controls: the same checks on a copy of the table with one defect planted, each caught with its message
rows = list(names.ROWS)
dropped = rows.pop(5)
s.eq("control, a missing row (%s): caught" % dropped[1],
     problems(rows, names.UNCHANGED, names.GONE, found, listed), ["no row for the command: %s" % dropped[1]])
rows = list(names.ROWS) + [("make ghost", "state nosuch")]
s.eq("control, a row for a ghost command: caught",
     problems(rows, names.UNCHANGED, names.GONE, found, listed), ["a row names a command that does not exist: state nosuch"])
rows = list(names.ROWS) + [(names.ROWS[0][0], "state nosuch")]
got = problems(rows, names.UNCHANGED, names.GONE, found, listed)
s.ok("control, a duplicate new name: caught", "two rows give the new name %r" % names.ROWS[0][0] in got, str(got))
rows = list(names.ROWS) + [("state", "state nosuch")]
got = problems(rows, names.UNCHANGED, names.GONE, found, listed)
s.ok("control, a one-word new name: caught", any("is not a verb and a noun" in x for x in got), str(got))
rows = list(names.ROWS) + [("model big", "state nosuch")]
got = problems(rows, names.UNCHANGED, names.GONE, found, listed)
s.ok("control, a verb that is a command of today: caught", any("would never be looked up" in x for x in got), str(got))

# ---- `fwx <show statusline>` stays fast: only the statusline module and the names table are imported (boom.py above) --------
if os.environ.get("FWX_TIMING") == "1":
    import statistics
    import time
    times = []
    for i in range(10):
        t0 = time.perf_counter()
        helpers.fwx(nogit, *new_of("statusline"), input="")
        times.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(times)
    print("timing: fwx %s median %.1f ms of 10 (min %.1f, max %.1f)" % (" ".join(new_of("statusline")), med, min(times), max(times)))
    s.ok("timing: the verb-first statusline, median of 10 runs under 100 ms", med < 100, "median %.1f ms" % med)
else:
    print("timing: SKIP (set FWX_TIMING=1)")

s.done()
