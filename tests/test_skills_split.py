#!/usr/bin/env python3
"""Step 2 of docs/toolchain-design.md: `forge sync` syncs projects only, `forge skills` owns the skill links
and the GSD runtime, and session start checks and tells without fixing.

1. `forge sync --all` runs agent config and system doc and nothing else; `forge skills` runs skill links and
   the GSD runtime (with gsd off, the second says NOT RUN, NOT ARMED).
2. A session start asks `sync_gsd_runtime.py --check --all` (never `--apply`, never run under the lock) and
   prints one note when it exits 2 (the runtime differs: names `forge skills --apply`) or 1 (the check
   failed: its '!' lines and `forge skills`); an in-sync runtime and gsd off are silent. A failing
   `toolchain` row adds one note naming `forge toolchain --fix`; a passing, warning or skipped one adds none.

Seen failing on 26a3ed5 (before the split), each by the message the check printed:
  (1) "forge sync --all still runs skill links, gsd runtime"; "forge skills: exit 2, `forge: error: argument
      cmd: invalid choice: 'skills'`"; "cli.SKILLS: AttributeError: module 'forge.cli' has no attribute 'SKILLS'"
  (2) "gsd differs: no note" (the old session start ran the step with --apply and printed nothing for it);
      "gsd differs: lib.run was called with --apply"; "toolchain FAIL: no note".
Controls: (2)'s silent cases and the gsd-off case pass on the old code and are the controls on the notes
(each note must appear only for its own cause); (1)'s `forge skills` case is armed by its own precondition,
that its output holds both headers, so an empty run never passes. The result of each mutation of the finished
code is in the commit message that added this file."""
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
check("forge skills (a dry-run) runs its three steps and exits 0",
      code == 0 and steps == ["== forge: online skills ==", "== forge: gsd runtime == NOT RUN, NOT ARMED (gsd off)", "== forge: skill links =="],
      "exit %d: %s" % (code, tail(out)))

check("cli.SKILLS names online skills, gsd runtime and skill links, in that order", [s[0] for s in getattr(cli, "SKILLS", [])] == ["online skills", "gsd runtime", "skill links"],
      "%s" % [s[0] for s in getattr(cli, "SKILLS", [])])
check("cli.SYNC names agent config and system doc", [s[0] for s in cli.SYNC] == ["agent config", "system doc"],
      "%s" % [s[0] for s in cli.SYNC])

# --- 2. what a session start says, with the steps, the lock and the project resolver stubbed out
REAL = (lib.run, lib.on, lib.lock, lib.resolve_project, lib.profiles, cli.session_wait, toolchain.row, cli.SYNC)


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
    lib.resolve_project, lib.profiles = (lambda path: "p"), (lambda skipped=None: {"p": {}})
    cli.session_wait, toolchain.row, cli.SYNC = (lambda: None), (lambda: row), []
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            cli.cmd_session_start(None)
    finally:
        lib.run, lib.on, lib.lock, lib.resolve_project, lib.profiles, cli.session_wait, toolchain.row, cli.SYNC = REAL
    msg = json.loads(out.getvalue())["systemMessage"] if out.getvalue().strip() else ""
    return msg, ran, held


msg, ran, held = session(gsd_exit=2)
check("gsd differs: one note naming forge skills --apply", "forge skills --apply" in msg and msg.count("GSD runtime") == 1, "message %r" % msg)
check("gsd differs: the check is `sync_gsd_runtime.py --check --all`, read-only, outside the lock",
      ran == [["scripts/sync/sync_gsd_runtime.py", "--check", "--all"]] and held == [False], "ran %s, lock held %s" % (ran, held))
check("gsd differs: lib.run was given something, and never --apply", bool(ran) and all("--apply" not in a for a in ran), "ran %s" % ran)

msg, ran, _ = session(gsd_exit=0)
check("gsd in sync and toolchain passing: silent", msg == "", "message %r" % msg)

msg, ran, _ = session(gsd_exit=1, gsd_out="! @opengsd/gsd-core not found under mise or `npm root -g` -- run `forge toolchain --fix`\nnoise\n")
check("gsd check failed: its '!' line and forge skills, once", msg.count("@opengsd/gsd-core not found") == 1 and "forge skills" in msg and "noise" not in msg,
      "message %r" % msg)

msg, ran, _ = session(gsd_exit=2, gsd_on=False)
check("gsd off: no check is run and nothing is said", msg == "" and ran == [], "message %r, ran %s" % (msg, ran))

msg, _, _ = session(row=lib.Result("FAIL", "toolchain", "1 failing: pip:PyYAML (checked 1 tool(s))"))
check("toolchain FAIL: one note with the row's detail and forge toolchain --fix",
      "1 failing: pip:PyYAML" in msg and "forge toolchain --fix" in msg and "GSD" not in msg, "message %r" % msg)
for level in ("WARN", "SKIP", "PASS"):
    msg, _, _ = session(row=lib.Result(level, "toolchain", "whatever"))
    check("toolchain %s: silent" % level, msg == "", "message %r" % msg)

print("%d check(s), %d failure(s)" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
