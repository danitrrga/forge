#!/usr/bin/env python3
"""Step 2 of docs/toolchain-design.md: `forge sync` syncs projects only, `forge skills` owns the skill links,
and session start checks and tells without fixing.

1. `forge sync --all` runs agent config and system doc and nothing else; `forge skills` runs online skills and
   skill links, and no GSD runtime step whether the `gsd` integration is off or on.
2. A session start runs no command that names the GSD runtime script and prints no GSD note, with `gsd` on or
   off. A failing `toolchain` row adds one note naming `forge toolchain --fix`; a passing, warning or skipped one
   adds none.

Seen failing on the code that still built and watched the GSD runtime (c0309a2), each by the message the check printed:
  (1) "forge skills prints the gsd runtime step: ... steps ['== forge: online skills ==', '== forge: gsd runtime ==',
      '== forge: skill links ==']" (gsd on) and, with gsd off, "forge skills (a dry-run) runs its two steps and exits 0"
      with the `NOT RUN, NOT ARMED (gsd off)` line among them
  (2) "gsd on: a session start runs no command naming sync_gsd_runtime.py: ran
      [['scripts/sync/sync_gsd_runtime.py', '--check', '--all']]"; "... prints no GSD note: message
      \"GSD runtime differs from forge's patched copy -- run `forge skills --apply`\""
Controls: the toolchain cases pass on the old code and are the controls on the notes (each note must appear
only for its own cause); (1)'s `forge skills` cases are armed by their own precondition, that the output holds
both remaining headers, so an empty run never passes."""
import contextlib
import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import sandbox  # noqa: E402
from forge import cli, lib, toolchain  # noqa: E402

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))
        print("FAIL", label, "--", detail)


def tail(text, n=4):
    return " | ".join(text.strip().splitlines()[-n:])


# --- 1. the commands, in a toy world with every integration off
top = sandbox.mkdtemp("skills-split-test-")
root, home, tmp = (os.path.join(top, d) for d in ("forge", "home", "tmp"))
for d in (home, tmp):
    os.makedirs(d)
sandbox.copy_engine(root)
sandbox.seed(root)
fj = os.path.join(root, "config", "forge.json")
doc = json.load(open(fj))
doc["integrations"] = {n: False for n in doc["integrations"]}
json.dump(doc, open(fj, "w"))
ENV = sandbox.bare_env(home, tmp)


def forge(*args):
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root, env=ENV,
                       capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


code, out = forge("sync", "--all")
steps = [l for l in out.splitlines() if l.startswith("== forge:")]
check("forge sync --all runs agent config and system doc, in that order",
      steps == ["== forge: agent config ==", "== forge: system doc =="], "steps %s" % steps)

code, out = forge("skills")
steps = [l for l in out.splitlines() if l.startswith("== forge:")]
check("forge skills (a dry-run) runs its two steps and exits 0",
      code == 0 and steps == ["== forge: online skills ==", "== forge: skill links =="],
      "exit %d: %s" % (code, tail(out)))

# The same world with the gsd integration ON: the step used to run (and, in a toy home, report on the runtime).
doc["integrations"]["gsd"] = True
json.dump(doc, open(fj, "w"))
code, out = forge("skills")
steps = [l for l in out.splitlines() if l.startswith("== forge:")]
check("forge skills with gsd on has no gsd runtime step", not any("gsd runtime" in l for l in steps),
      "forge skills prints the gsd runtime step: steps %s" % steps)
check("forge skills with gsd on still runs online skills and skill links, in that order",
      steps == ["== forge: online skills ==", "== forge: skill links =="], "exit %d, steps %s" % (code, steps))

check("cli.SKILLS names online skills and skill links, in that order", [s[0] for s in getattr(cli, "SKILLS", [])] == ["online skills", "skill links"],
      "%s" % [s[0] for s in getattr(cli, "SKILLS", [])])
check("cli.SYNC names agent config and system doc", [s[0] for s in cli.SYNC] == ["agent config", "system doc"],
      "%s" % [s[0] for s in cli.SYNC])

# --- 2. what a session start says, with the steps, the lock and the project resolver stubbed out
REAL = (lib.run, lib.on, lib.lock, lib.resolve_project, lib.projects, cli.session_wait, toolchain.row, cli.SYNC)


def session(gsd_exit=0, gsd_out="", row=lib.Result("PASS", "toolchain", "all present"), gsd_on=True):
    """(systemMessage or "", every argv lib.run was given, whether the lock was held while it ran)."""
    ran, held, locked = [], [], [False]

    class Lock:
        def __enter__(self):
            locked[0] = True

        def __exit__(self, *a):
            locked[0] = False

    def run(args, capture=False, env=None, low=False):
        ran.append(list(args))
        held.append(locked[0])
        return subprocess.CompletedProcess(args, gsd_exit, gsd_out, "")
    lib.run, lib.on, lib.lock = run, (lambda name: gsd_on and name == "gsd"), (lambda timeout=20: Lock())
    lib.resolve_project, lib.projects = (lambda path: "p"), (lambda skipped=None: {"p": {}})
    cli.session_wait, toolchain.row, cli.SYNC = (lambda: None), (lambda: row), []
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            cli.cmd_session_start(None)
    finally:
        lib.run, lib.on, lib.lock, lib.resolve_project, lib.projects, cli.session_wait, toolchain.row, cli.SYNC = REAL
    msg = json.loads(out.getvalue())["systemMessage"] if out.getvalue().strip() else ""
    return msg, ran, held


# Whatever the stubbed lib.run would answer for a GSD check (exit 2: "differs", exit 1: failed), a session start
# no longer asks it: no command names the script, and no GSD note is printed. Gsd on and off alike.
for gsd_on in (True, False):
    for gsd_exit in (2, 1, 0):
        msg, ran, _ = session(gsd_exit=gsd_exit, gsd_out="! some check failed\n", gsd_on=gsd_on)
        check("gsd %s, a check that would exit %d: a session start runs no command naming sync_gsd_runtime.py" % ("on" if gsd_on else "off", gsd_exit),
              not any("sync_gsd_runtime.py" in a for argv in ran for a in argv), "ran %s" % ran)
        check("gsd %s, a check that would exit %d: a session start prints no GSD note and runs nothing" % ("on" if gsd_on else "off", gsd_exit),
              msg == "" and ran == [], "message %r, ran %s" % (msg, ran))

msg, _, _ = session(row=lib.Result("FAIL", "toolchain", "1 failing: pip:PyYAML (checked 1 tool(s))"))
check("toolchain FAIL: one note with the row's detail and forge toolchain --fix",
      "1 failing: pip:PyYAML" in msg and "forge toolchain --fix" in msg and "GSD" not in msg, "message %r" % msg)
for level in ("WARN", "SKIP", "PASS"):
    msg, _, _ = session(row=lib.Result(level, "toolchain", "whatever"))
    check("toolchain %s: silent" % level, msg == "", "message %r" % msg)

print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
