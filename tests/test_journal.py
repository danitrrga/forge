#!/usr/bin/env python3
"""The change journal (increment I1 of step 10): `forge sync --apply` and `forge session-start` append
one line per change they made on disk to ~/.local/state/forge/journal.log, and `forge log [--since DATE]
[NAME]` prints it. A line is `<ISO8601 local time> <cmd> <step> <what> <path>`: paths only, never
content, so never a secret. The journal keeps its last 10000 lines. A dry-run neither creates nor touches it.

The world is W/forge (an engine-only copy, git init'd), W/home (the HOME of every command) and
W/projects/toy-a, toy-b (the shape lib.may_write allows a toy HOME to write). Every integration is off,
so nothing reaches for npm or the network. toy-a's profile resolves ${FAKE_TOKEN} into its env; the value
is fake and nothing real is read or written. Case (d) calls lib.journal in a subprocess of the toy checkout,
because lib.may_write() refuses an in-process write from a linked worktree or against the real HOME.

Seen failing on e2ec8e6, before lib.journal and `forge log` existed (every journal check red):
  (a) sync --apply leaves a `wrote` line for toy-a's settings.local.json -- there is no journal at
      <W>/home/.local/state/forge/journal.log
  (c) forge log toy-a -- exit 2, `forge: error: argument cmd: invalid choice: 'log' (choose from 'sync',
      'doctor', 'metrics', 'test', 'toolchain', 'session-start', 'check-public', 'commit', 'init', 'add')`
  (d) lib.journal keeps the last 10000 lines -- AttributeError: module 'forge.lib' has no attribute 'journal'
  (f) session-start appends a `session-start` line -- there is no journal
Check (b) passes on the old code, as it must: nothing was ever written there. (e) is red there too, for
the right reason: it fails at a journal with no lines, because looking at zero is a failure; and it is armed
by its own precondition, that the token did reach toy-a's settings.local.json, so a journal with nothing to
leak is never mistaken for one that does not leak.
Negative control on the finished code, put back from a copy of forge/cli.py: with the line that sets
FORGE_WRITE_LOG for each step of cmd_sync removed, (a) goes red again: the journal is never made. The
result is in the commit message that added this file."""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures, n_checks = [], [0]
FAKE_TOKEN = "fake-journal-token-5d2e-NOT-REAL"
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d ")


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))
        print("FAIL", label, "--", detail)


def tail(text, n=4):
    return " | ".join(text.strip().splitlines()[-n:])


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


top = sandbox.mkdtemp("journal-test-")
root, home, tmp = (os.path.join(top, d) for d in ("forge", "home", "tmp"))
projects = {n: os.path.join(top, "projects", n) for n in ("toy-a", "toy-b")}
for d in [home, tmp] + list(projects.values()):
    os.makedirs(d)
sandbox.copy_engine(root)
sandbox.seed(root)
sandbox.git(root, "init", "-q")
sandbox.git(root, "add", "-A")
sandbox.git(root, "commit", "-q", "-m", "engine")

cfg = os.path.join(root, "config")
fj = json.load(open(os.path.join(cfg, "forge.json")))
fj["integrations"] = {n: False for n in fj["integrations"]}
fj["codex_harness"] = False
write_json(os.path.join(cfg, "forge.json"), fj)
for f in os.listdir(os.path.join(cfg, "profiles")):  # the fixture's profiles name /srv/toy/*, outside the world
    os.remove(os.path.join(cfg, "profiles", f))
for name, env in (("toy-a", {"FAKE_TOKEN": "${FAKE_TOKEN}"}), ("toy-b", {"PLAIN": "1"})):
    write_json(os.path.join(cfg, "profiles", name + ".claude.json"),
               {"project": name, "project_path": projects[name], "enableAllProjectMcpServers": True, "servers": [],
                "env": env, "plugins_keep": [], "skills_keep": ["*"], "permissions": {}})
write_json(os.path.join(root, "credentials", "secrets.json"), {"FAKE_TOKEN": FAKE_TOKEN})
os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))

ENV = sandbox.bare_env(home, tmp)
JOURNAL = os.path.join(home, ".local", "state", "forge", "journal.log")


def forge(*args, env=None):
    r = subprocess.run([sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root,
                       env=env or ENV, capture_output=True, text=True, timeout=600)
    return r.returncode, r.stdout + r.stderr


def journal_lines():
    return open(JOURNAL, encoding="utf-8").read().splitlines() if os.path.exists(JOURNAL) else []


def fields(line):
    return line.split(" ", 4)  # time, cmd, step (no spaces), what, path


def sl(name):
    return os.path.join(projects[name], ".claude", "settings.local.json")


# (b) a dry-run never creates the journal.
code, out = forge("sync", "--all")
check("(b) forge sync --all dry-run exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
check("(b) a dry-run does not create the journal", not os.path.exists(JOURNAL), "%s exists" % JOURNAL)

# (a) an apply leaves a `wrote` line naming the project's settings.local.json.
code, out = forge("sync", "--apply", "--project", "toy-a")
check("(a) sync --apply --project toy-a exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
check("(a) toy-a's settings.local.json exists", os.path.exists(sl("toy-a")), "missing %s" % sl("toy-a"))
lines = journal_lines()
mine = [fields(l) for l in lines if len(fields(l)) == 5 and fields(l)[3] == "wrote" and fields(l)[4] == sl("toy-a")]
check("(a) sync --apply leaves a `wrote` line for toy-a's settings.local.json (%d lines in the journal)" % len(lines), len(mine) == 1,
      "there is no journal at %s" % JOURNAL if not lines else "lines: %s" % lines[:3])
check("(a) the line is `<ISO8601 time> sync <step> wrote <path>`", bool(mine) and bool(STAMP.match(lines[0])) and mine[0][1] == "sync" and mine[0][2] == "agent-config",
      "fields %s" % (mine[:1],))
check("(a) every line of the journal has the five fields and a stamp", bool(lines) and all(STAMP.match(l) and len(fields(l)) == 5 for l in lines), "lines: %s" % lines[:3])

# (e) a secret the profile resolves into env reaches the file, and never the journal.
body = open(sl("toy-a")).read() if os.path.exists(sl("toy-a")) else ""
check("(e) precondition: the fake token is in toy-a's settings.local.json (else the check looks at nothing)", FAKE_TOKEN in body, "not resolved")
check("(e) the journal never holds the token", bool(lines) and FAKE_TOKEN not in "\n".join(lines), "found in the journal")

# (b, again) a dry-run after the journal exists leaves it byte- and mtime-identical.
before = (open(JOURNAL, "rb").read(), os.stat(JOURNAL).st_mtime_ns) if lines else None
code, out = forge("sync", "--all")
after = (open(JOURNAL, "rb").read(), os.stat(JOURNAL).st_mtime_ns) if os.path.exists(JOURNAL) else None
check("(b) a dry-run leaves an existing journal untouched", before is not None and before == after, "before/after differ or the journal is missing")

# (c) forge log NAME prints that project's lines and not another project's.
code, out = forge("sync", "--apply", "--project", "toy-b")
check("(c) sync --apply --project toy-b exits 0", code == 0, "exit %d: %s" % (code, tail(out)))
code, out = forge("log", "toy-a")
check("(c) forge log toy-a exits 0 and prints toy-a's line", code == 0 and sl("toy-a") in out, "exit %d: %s" % (code, tail(out)))
check("(c) forge log toy-a prints nothing of toy-b", sl("toy-b") not in out and projects["toy-b"] not in out, tail(out, 8))
code, out = forge("log")
check("(c) forge log with no name prints both projects", code == 0 and sl("toy-a") in out and sl("toy-b") in out, "exit %d: %s" % (code, tail(out)))
code, out = forge("log", "--since", "2999-01-01", "toy-a")
check("(c) forge log --since a future day prints nothing", code == 0 and out.strip() == "", "exit %d: %s" % (code, tail(out)))
code, out = forge("log", "--since", "1999-01-01", "toy-a")
check("(c) forge log --since a past day prints toy-a's line", code == 0 and sl("toy-a") in out, "exit %d: %s" % (code, tail(out)))
code, out = forge("log", "no-such-project")
check("(c) forge log of an unknown project exits 1 and says so", code == 1 and "no-such-project" in out, "exit %d: %s" % (code, tail(out)))
code, out = forge("log", "--since", "yesterday")
check("(c) forge log --since a non-date exits nonzero and says so", code != 0 and "--since" in out, "exit %d: %s" % (code, tail(out)))

# (d) past 10000 lines the journal keeps the last ones.
old = ["1999-06-01T00:00:00+00:00 sync agent-config wrote /old/%d" % i for i in range(10005)]
with open(JOURNAL, "w", encoding="utf-8") as fh:
    fh.write("\n".join(old) + "\n")
snippet = "from forge import lib; lib.journal([('wrote', '/new/%d' % i) for i in range(3)], 'sync', 'agent config')"
r = subprocess.run([sys.executable, "-c", snippet], cwd=root, env=ENV, capture_output=True, text=True)
kept = journal_lines()
check("(d) lib.journal keeps the last 10000 lines (%d kept)" % len(kept), r.returncode == 0 and len(kept) == 10000,
      "exit %d, %d lines: %s" % (r.returncode, len(kept), tail(r.stderr)))
check("(d) the oldest are the ones dropped and the new ones are last",
      len(kept) == 10000 and kept[0].endswith("/old/8") and fields(kept[-1])[4] == "/new/2" and fields(kept[-1])[2] == "agent-config",
      "first %r, last %r" % (kept[:1], kept[-1:]))
r = subprocess.run([sys.executable, "-c", "from forge import lib; lib.journal([], 'sync', 'x')"], cwd=root, env=ENV, capture_output=True, text=True)
check("(d) no lines changes nothing", r.returncode == 0 and len(journal_lines()) == 10000, "exit %d, %d lines" % (r.returncode, len(journal_lines())))

# (f) session-start appends too, and its notice still names what it wrote.
os.remove(JOURNAL)
os.remove(sl("toy-b"))
code, out = forge("session-start", env=dict(ENV, CLAUDE_PROJECT_DIR=projects["toy-b"]))
mine = [fields(l) for l in journal_lines() if len(fields(l)) == 5 and fields(l)[3] == "wrote" and fields(l)[4] == sl("toy-b")]
check("(f) session-start appends a `session-start` line for toy-b's settings.local.json", len(mine) == 1 and mine[0][1] == "session-start",
      "exit %d, lines %s, output %s" % (code, journal_lines()[:3], tail(out)))
check("(f) the start-up notice is JSON that still names the step and the file", code == 0 and "agent config:" in out and "settings.local.json" in out, tail(out))
leftovers = [f for f in os.listdir(tmp) if f.startswith("forge-writes-")]
check("(f) session-start still removes its temp write log", leftovers == [], "left %s" % leftovers)

sandbox.cleanup(bool(failures))
if failures:
    print("\n%d of %d checks failed" % (len(failures), n_checks[0]))
    sys.exit(1)
print("test_journal: %d checks passed" % n_checks[0])
