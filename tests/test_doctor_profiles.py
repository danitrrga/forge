#!/usr/bin/env python3
"""The `profiles` row of `forge doctor` and `forge doctor NAME` (forge/profiles.py doctor_row, wired in forge/cli.py): for each
project that declares `profiles`, every offered profile resolves, is not empty and has session files that can be built
(launch.session_files: the --settings and --mcp-config documents, which write nothing); a secret a profile's server or env
names that the store lacks is a FAIL naming the profile and the secret's NAME, never its value; the row says how many projects
and profiles it looked at, and is a SKIP, NOT RUN, NOT ARMED when no project declares profiles. `claude` off PATH is a FAIL only
when a project declares profiles.

The world is test_profiles' (an engine copy, a toy HOME, tests/sandbox.py) with its own projects:
  good     two profiles that resolve (toy-b, list)
  none     no `profiles`;  frozen-p  declares them and is frozen (it receives none)
  skillbad a profile naming a skill that is not installed
  emptyp   a profile whose definition and row contribute no skill, no plugin and no server
  secbad   a profile whose server and env name a secret the toy store lacks
  secok    a profile whose server and env name secrets the store has (their values are planted: the output may not carry them)
  noof     `profiles` with an empty `offered`
The rows run through a child that keeps only the `profiles` row of cmd_doctor (fast, and the PATH can be bare), and `forge doctor`
and `forge doctor NAME` run whole for the first cases.

Cases (the brief's six, numbered as it numbers them, then the PATH):
  1 a missing skill is `FAIL profiles ... <project>/<profile>: unknown skill`, in both forms
  2 two good profiles are a PASS whose detail counts projects and profiles
  3 no project declares `profiles` (frozen ones included): SKIP, NOT RUN, NOT ARMED, both forms; `forge doctor NAME` of a project
    without `profiles` is the same SKIP in a world where another project has them
  4 a profile that resolves to nothing: FAIL naming it
  5 a missing secret: FAIL naming the profile and the secret, the planted values in no output
  6 projects with `profiles` and zero profiles looked at: FAIL (a project with `offered: {}`; and a copy of the engine whose loop is
    emptied)
  7 claude off PATH: FAIL naming the fix with a project that declares profiles, no word of it when none does
and the row writes nothing.

Written first, run against the code with no `profiles` row: 31 FAIL, each on a doctor that printed no such line ("FAIL 1: a
missing skill is reported in the aggregate row (child, aggregate) -- missing skill not reported: None ''", "FAIL 2: two good
profiles are a PASS that counts (forge doctor) -- got None ''", "FAIL 3: no project declares `profiles`: SKIP, NOT RUN, NOT
ARMED (forge doctor) -- got None ''", "FAIL 0: the row writes nothing" aside, which was the whole doctor's own journal and
moved to the child forms), then a traceback in the last case: the engine copy had no loop to empty.
Negative controls, each a mutation made by hand in forge/profiles.py (the script that applied them is not kept), run once; the
first message of the case each one broke:
  1  _problem swallowing a ProfileError (`return None`) -> "FAIL 1: a missing skill is reported in the aggregate row (child,
     aggregate) -- missing skill not reported: FAIL 'looked at 5 project(s) (emptyp, good, secbad, secok, skillbad), 6 profile(s):
     emptyp/empty: resolves to nothing: ..." (4 FAIL: the skill, in both forms of both rows)
  4  the emptiness test dropped -> "FAIL 4: a profile that resolves to nothing is a FAIL (child) -- got PASS 'looked at 1 project(s)
     (emptyp), 1 profile(s): each resolves, adds something of its own and has session files that build; ...'" (3 FAIL)
  5  launch.session_files not called -> "FAIL 5: a missing secret names the profile and the secret (child, aggregate) -- got FAIL
     'looked at 5 project(s) ...: emptyp/empty: ... | skillbad/err-skill: ...'" with no secbad line (4 FAIL)
  5  the store's text appended to the message of a ProfileError -> "FAIL 5: no planted secret value in any output (child,
     aggregate) -- planted value in output" (4 FAIL)
  6  the `if not looked` test dropped -> "FAIL 6: offered {} is a FAIL (child, aggregate) -- got PASS 'looked at 1 project(s)
     (noof), 0 profile(s): each resolves, ...'" (5 FAIL)
  7  the claude lookup replaced by a constant -> "FAIL 7: claude off PATH is a FAIL naming the fix -- got PASS 'looked at 1 project(s)
     (good), 2 profile(s): ...; claude is at /x/claude'" (2 FAIL)
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
import test_profiles as tp  # noqa: E402

failures = []
PLANT_A, PLANT_B = "planted-secret-value-AAA-7731", "planted-secret-value-BBB-4409"
SKILLS = tp.SKILLS + ("toy-other",)
NOT_ARMED = "NOT RUN, NOT ARMED"
# The child keeps the `profiles` row of the doctor, in both forms, and runs the real cmd_doctor over it.
CHILD = """import argparse, sys
from forge import cli
only = sys.argv[1] if len(sys.argv) > 1 else None
keep = lambda rows: [r for r in rows if r[0] == "profiles"]
every = cli.project_checks
if only:  # project_checks reads CHECKS for its fix texts, so CHECKS is cut only for the aggregate form
    cli.project_checks = lambda name, prof, why: keep(every(name, prof, why))
else:
    cli.CHECKS = keep(cli.CHECKS)
sys.exit(cli.cmd_doctor(argparse.Namespace(project=only)))
"""

DEFS = {
    "empty": {"description": "contributes nothing"},
    "toy-sec": {"description": "a server and an env that name a missing secret", "color": "green", "skills": ["toy-a"],
                "server_kinds": ["vault"], "env": {"TOY_SECRET_ENV": "${TOY_TOKEN}"}},
    "toy-sec-ok": {"description": "secrets the store has", "color": "green", "skills": ["toy-a"], "server_kinds": ["vault"],
                   "env": {"TOY_ENV_OK": "${TOY_TOKEN_ENV_OK}"}},
}
PROJECTS = {
    "good": {"profiles": {"default": "code", "offered": {
        "toy-b": {"skills": ["toy-c"], "plugins": ["toy-plugin@x"], "servers": {"analytics": "toy-echo"}}, "list": {}}}},
    "skillbad": {"profiles": {"default": "code", "offered": {"err-skill": {}}}},
    "emptyp": {"profiles": {"default": "code", "offered": {"empty": {}}}},
    "secbad": {"profiles": {"default": "code", "offered": {"toy-sec": {"servers": {"vault": "toy-sec"}}}}},
    "secok": {"profiles": {"default": "code", "offered": {"toy-sec-ok": {"servers": {"vault": "toy-sec-ok"}}}}},
    "noof": {"profiles": {"default": "code", "offered": {}}},
}
REGISTRY = {"servers": {
    "toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}},
    "toy-sec": {"type": "stdio", "command": "toy-sec", "args": [], "env": {"TOY_TOKEN": "${TOY_TOKEN}"}},
    "toy-sec-ok": {"type": "stdio", "command": "toy-sec-ok", "args": [], "env": {"TOY_TOKEN_OK": "${TOY_TOKEN_OK}"}}}}
SECRETS = {"TOY_OTHER": PLANT_A, "TOY_TOKEN_OK": PLANT_B, "TOY_TOKEN_ENV_OK": PLANT_B}  # no TOY_TOKEN: secbad's is missing


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


def world(names, **kw):
    """A tp.World of `names`, with this test's definitions, registry and secrets, and a fake `claude` and a python3 and git in a
    bin directory of its own (never executed: the row only looks for it)."""
    tp.DEFS.update(DEFS)
    tp.PROJECTS.update(PROJECTS)
    w = tp.World(names, skills=SKILLS, **kw)
    tp.write_json(os.path.join(w.forge, "config", "mcp-registry.json"), REGISTRY)
    tp.write_json(os.path.join(w.forge, "credentials", "secrets.json"), SECRETS)
    w.fakebin = os.path.join(w.root, "fakebin")
    os.makedirs(w.fakebin)
    with open(os.path.join(w.fakebin, "claude"), "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(w.fakebin, "claude"), 0o755)
    os.symlink(sys.executable, os.path.join(w.fakebin, "python3"))
    os.symlink(shutil.which("git"), os.path.join(w.fakebin, "git"))
    return w


def env(w, claude=True):
    """The toy environment. With claude, a directory holding a fake one is first on the real PATH; without it, PATH is that
    directory's python3 and git alone (ORDERS 10: the system directories behind it would find the real claude)."""
    e = sandbox.bare_env(w.home, w.root)
    if claude:
        e["PATH"] = w.fakebin + os.pathsep + e["PATH"]
    else:
        nobin = os.path.join(w.root, "nobin")
        if not os.path.isdir(nobin):
            os.makedirs(nobin)
            os.symlink(sys.executable, os.path.join(nobin, "python3"))
            os.symlink(shutil.which("git"), os.path.join(nobin, "git"))
        e["PATH"] = nobin
    return e


LINE = re.compile(r"^(PASS|FAIL|SKIP|WARN)\s+profiles\s+(.*)$", re.M)


def row(w, only=None, whole=False, claude=True):
    """(level, detail, the whole output) of the `profiles` row, or (None, '', output) when the doctor printed none."""
    if whole:
        cmd = [sys.executable, os.path.join(w.forge, "bin", "forge"), "doctor"] + ([only] if only else [])
    else:
        cmd = [sys.executable, "-c", CHILD] + ([only] if only else [])
    r = subprocess.run(cmd, cwd=w.forge, env=env(w, claude), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    out = (r.stdout + r.stderr).replace(w.root, "@S@")
    m = LINE.search(out)
    return (m.group(1), m.group(2), out) if m else (None, "", out)


def main():
    try:
        # World A: every way a profile fails, and a secret that resolves.
        a = world(["good", "none", "skillbad", "emptyp", "secbad", "secok"])
        for label, only, whole in (("child, aggregate", None, False), ("forge doctor", None, True),
                                   ("child, project", "skillbad", False), ("forge doctor skillbad", "skillbad", True)):
            lvl, det, out = row(a, only, whole)
            check("1: a missing skill is reported in the aggregate row (%s)" % label,
                  lvl == "FAIL" and "skillbad/err-skill: unknown skill" in det and "toy-missing" in det,
                  "missing skill not reported: %s %r" % (lvl, det))
        # The row writes nothing: not the session files (launch.session_files only builds them), not a state file. The whole
        # doctor is left out: its other rows write their own journal.
        before = sandbox.manifest(a.root)
        for only in (None, "good", "secok"):
            row(a, only, False)
        check("0: the row writes nothing", sandbox.manifest(a.root) == before,
              "changed: %s" % sorted(k for k, v in sandbox.manifest(a.root).items() if before.get(k) != v))

        for label, only, whole in (("child", "emptyp", False), ("forge doctor emptyp", "emptyp", True)):
            lvl, det, out = row(a, only, whole)
            check("4: a profile that resolves to nothing is a FAIL (%s)" % label,
                  lvl == "FAIL" and "emptyp/empty" in det and "nothing" in det, "got %s %r" % (lvl, det))
        lvl, det, out = row(a, None, False)
        check("4: ... and the aggregate names it", "emptyp/empty" in det, "got %s %r" % (lvl, det))

        for label, only, whole in (("child, aggregate", None, False), ("forge doctor", None, True),
                                   ("child, project", "secbad", False), ("forge doctor secbad", "secbad", True)):
            lvl, det, out = row(a, only, whole)
            check("5: a missing secret names the profile and the secret (%s)" % label,
                  lvl == "FAIL" and "secbad/toy-sec" in det and "TOY_TOKEN" in det, "got %s %r" % (lvl, det))
            check("5: no planted secret value in any output (%s)" % label, PLANT_A not in out and PLANT_B not in out,
                  "planted value in output")
        lvl, det, out = row(a, "secok", False)
        check("5: a secret that is there is a PASS and its value is not printed", lvl == "PASS" and "1 profile(s)" in det
              and PLANT_B not in out and PLANT_A not in out, "got %s %r" % (lvl, det))

        # World B: two good profiles, and a project without `profiles` beside them.
        b = world(["good", "none"])
        for label, only, whole in (("child, aggregate", None, False), ("forge doctor", None, True),
                                   ("child, project", "good", False), ("forge doctor good", "good", True)):
            lvl, det, out = row(b, only, whole)
            check("2: two good profiles are a PASS that counts (%s)" % label,
                  lvl == "PASS" and "1 project(s)" in det and "2 profile(s)" in det, "got %s %r" % (lvl, det))
        for label, whole in (("child", False), ("forge doctor none", True)):
            lvl, det, out = row(b, "none", whole)
            check("3: a project without `profiles` is the SKIP (%s)" % label, lvl == "SKIP" and NOT_ARMED in det, "got %s %r" % (lvl, det))
        # 7: claude. With a project that declares profiles, off PATH is a FAIL naming the fix; the profiles still counted.
        lvl, det, out = row(b, None, False, claude=False)
        check("7: claude off PATH is a FAIL naming the fix", lvl == "FAIL" and "claude" in det and "PATH" in det
              and "2 profile(s)" in det, "got %s %r" % (lvl, det))
        lvl, det, out = row(b, "good", False, claude=False)
        check("7: ... in the project form too", lvl == "FAIL" and "claude" in det, "got %s %r" % (lvl, det))

        # World C: nothing declares profiles (a frozen project declares them and receives none).
        c = world(["none", "frozen-p"])
        for label, only, whole in (("child, aggregate", None, False), ("forge doctor", None, True),
                                   ("child, project", "none", False), ("forge doctor none", "none", True),
                                   ("child, frozen project", "frozen-p", False)):
            lvl, det, out = row(c, only, whole)
            check("3: no project declares `profiles`: SKIP, NOT RUN, NOT ARMED (%s)" % label,
                  lvl == "SKIP" and NOT_ARMED in det, "got %s %r" % (lvl, det))
        lvl, det, out = row(c, None, False, claude=False)
        check("7: ... and claude is not looked for", lvl == "SKIP" and "claude" not in det, "got %s %r" % (lvl, det))

        # 6: profiles declared, zero looked at.
        e = world(["noof"])
        for label, only, whole in (("child, aggregate", None, False), ("forge doctor", None, True),
                                   ("child, project", "noof", False), ("forge doctor noof", "noof", True)):
            lvl, det, out = row(e, only, whole)
            check("6: offered {} is a FAIL (%s)" % label, lvl == "FAIL" and "0 profile(s)" in det, "got %s %r" % (lvl, det))
        anchor = '        for profile in prof["profiles"]["offered"]:  # the profiles looked at\n'
        f = world(["good"], mutate=("forge/profiles.py", anchor, "        for profile in []:  # the profiles looked at\n"))
        lvl, det, out = row(f, None, False)
        check("6: a loop that looks at nothing, in a project with two profiles, is a FAIL", lvl == "FAIL" and "0 profile(s)" in det,
              "got %s %r" % (lvl, det))
    finally:
        sandbox.cleanup()
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    print("test_doctor_profiles: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
