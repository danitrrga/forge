#!/usr/bin/env python3
"""relink_skills.py when a link cannot be made, repointed or pruned: each failure is named, the
other links and the other mirror still get done, the run exits 1, and a real directory in the
mirror is never deleted.

A copy of the script and forge/lib.py runs from a temp dir laid out like forge (forge/, home/
side by side, no profiles), with a temp HOME whose ~/.claude/skills is read-only and holds one
skill to link, one stale link to repoint, one dangling link to prune, one real directory and
one correct link; ~/.codex/skills is writable and empty. It runs in an empty network namespace
as this uid, not as the namespace's root (`unshare -rn`), which would ignore the 0555.

Seen failing on 4a0f180: "read-only mirror: exit 1, Traceback True, codex links [],
named ['beta']: ... | PermissionError: [Errno 13] Permission denied: '<home>/.claude/skills/beta'"
-- the first failure (the repoint's unlink) ended the run, and ~/.codex/skills was never reached.
The writable control passed on the same commit. A BLOCKED real dir still exits 0: that is a
skill authored in the wrong place, reported every run, not a failed run.

With CODEX_HOME set, the Codex mirror goes to $CODEX_HOME/skills, where Codex reads skills and
the generator writes $CODEX_HOME/hooks.json. Seen failing on 32f2e47: "CODEX_HOME=
<tmp>/ch: exit 0, $CODEX_HOME/skills links None, ~/.codex created True" -- the path was hardcoded.

A --dry-run prints the counts the apply then makes, on the same world. A dangling link named after
a current skill is one repoint: the dry-run, which never repoints it, also counted it as pruned.
Seen failing on b6222aa: "dry-run vs apply, dangling link named alpha: dry (8, 2),
apply (8, 1)". On a fresh HOME, with neither mirror there, the dry-run skipped each missing mirror
before counting and printed nothing while the apply made every link; it must count them and create
no directory. Seen failing on f62e1b6: "dry-run vs apply, fresh HOME: dry (0, 0), apply
(8, 0)". A mirror path that is a regular file fails the apply's makedirs; the dry-run names the same
failure rather than counting links it could never make ("dry exit 0, (0, 0), apply exit 1, (4, 0)"
on f62e1b6, the dry-run silent)."""
import os
import re
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "tests"))
import sandbox  # noqa: E402
from sandbox import tail  # noqa: E402

SKILLS = ("alpha", "beta", "gamma", "delta")
# relink reads integrations.codex, and the cases need it on. The fixture's forge.json has it on, and is in
# every checkout; this machine's config/forge.json is not, and would turn the codex cases off with the
# integration. Red before, on a copy_engine copy in a toy HOME (M1): "FileNotFoundError: .../config/forge.json"
# from make_root's copy of this checkout's file.
FIXTURE_JSON = os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "forge.json")
NS = ("unshare", "-n", "--map-user=%d" % os.getuid(), "--map-group=%d" % os.getgid())


def bare_root():
    """forge/ with the four skills and an empty toy HOME: no ~/.claude, no ~/.codex."""
    tmp = sandbox.mkdtemp("relink-test-")
    root = os.path.join(tmp, "forge")
    os.makedirs(os.path.join(root, "config", "profiles"))
    sandbox.mini_root(root, os.path.join("scripts", "sync", "relink_skills.py"))
    shutil.copy(FIXTURE_JSON, os.path.join(root, "config", "forge.json"))  # relink reads integrations.codex
    for n in SKILLS:
        os.makedirs(os.path.join(root, "skills", n))
    os.makedirs(os.path.join(tmp, "home"))
    return tmp


def make_root(read_only, codex=True):
    tmp = sandbox.mkdtemp("relink-test-")
    root = os.path.join(tmp, "forge")
    os.makedirs(os.path.join(root, "config", "profiles"))
    sandbox.mini_root(root, os.path.join("scripts", "sync", "relink_skills.py"))
    shutil.copy(FIXTURE_JSON, os.path.join(root, "config", "forge.json"))  # relink reads integrations.codex
    for n in SKILLS:
        os.makedirs(os.path.join(root, "skills", n))
        with open(os.path.join(root, "skills", n, "SKILL.md"), "w") as f:
            f.write("---\nname: %s\n---\n" % n)
    os.makedirs(os.path.join(tmp, "elsewhere", "beta"))
    mirror = os.path.join(tmp, "home", ".claude", "skills")
    os.makedirs(mirror)
    if codex:
        os.makedirs(os.path.join(tmp, "home", ".codex", "skills"))
    os.symlink(os.path.join(tmp, "elsewhere", "beta"), os.path.join(mirror, "beta"))  # stale: repoint
    os.symlink(os.path.join(tmp, "nonexistent"), os.path.join(mirror, "gone"))  # dangling: prune
    os.makedirs(os.path.join(mirror, "gamma"))  # a real dir: blocked, never deleted
    with open(os.path.join(mirror, "gamma", "SKILL.md"), "w") as f:
        f.write("authored in the wrong place\n")
    os.symlink(os.path.join(root, "skills", "delta"), os.path.join(mirror, "delta"))  # already right
    if read_only:
        os.chmod(mirror, 0o555)
    return tmp


RULE = []  # runs that broke the exit rule, reported as failures by main()


def run(tmp, *args, **extra):
    """relink_skills.py on the toy world. Every run is held to forge/sync.py agent_config's exit
    rule, which this step keeps too: a line whose first non-space character is '!' means exit 1,
    and no other line does (forge/cli.py's CHANGED shows the FAILED summary by its '!' alone).
    Red on 2d539e7^'s relink_skills.py, before the summary's "! " prefix: "exit rule:
    exit 1, no '!' line: relink_skills: 4 skills | 4 linked, 0 pruned | BLOCKED(real dir in
    mirror): <t>/home/.claude/skills/gamma | FAILED: <t>/home/.claude/skills/beta (Permission
    denied), ..." for the read-only mirror, and "exit rule: exit 1, no '!' line: relink_skills: 4
    skills | 4 would be linked, 0 would be pruned | FAILED: <t>/home/.codex/skills (File exists)"
    with its apply for a mirror that is a file."""
    env = sandbox.bare_env(os.path.join(tmp, "home"), tmp, **extra)
    r = subprocess.run(list(NS) + [sys.executable, os.path.join(tmp, "forge", "scripts", "sync", "relink_skills.py")]
                       + list(args), cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       timeout=60)
    bang = re.search(r"(?m)^\s*!", r.stdout)
    if bool(bang) != (r.returncode != 0):
        RULE.append("exit rule: exit %d, %s: %s" % (r.returncode, "a '!' line" if bang else "no '!' line",
                                                     tail(r.stdout.replace(tmp, "<t>"), 1)))
    return r.returncode, r.stdout


def counts(out):
    """(linked, pruned) from the summary line; no line is (0, 0), what a run with nothing to do prints."""
    m = re.search(r"(\d+) (?:would be )?linked, (\d+) (?:would be )?pruned", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def parity(label, tmp, failures):
    """The dry-run's counts, then the apply's, on the same world: they must match."""
    rc_dry, dry = run(tmp, "--dry-run")
    rc, out = run(tmp)
    if rc_dry or rc or counts(dry) != counts(out):
        failures.append("dry-run vs apply, %s: dry %s, apply %s: %s | %s"
                        % (label, counts(dry), counts(out), tail(dry, 1), tail(out, 1)))
    return out


def links(tmp, mirror):
    """The skills correctly linked in <mirror>/skills. `mirror` is relative to the toy HOME, or
    absolute ($CODEX_HOME), which os.path.join lets replace the HOME prefix."""
    d = os.path.join(tmp, "home", mirror, "skills")
    src = os.path.join(tmp, "forge", "skills")
    return sorted(n for n in os.listdir(d) if os.path.islink(os.path.join(d, n))
                  and os.path.realpath(os.path.join(d, n)) == os.path.join(src, n))


def gamma_intact(tmp):
    p = os.path.join(tmp, "home", ".claude", "skills", "gamma")
    return (not os.path.islink(p) and os.path.isfile(os.path.join(p, "SKILL.md")))


def main():
    ok, detail = sandbox.unshare_ok(NS)
    if not ok:
        print("FAIL no empty network namespace (unshare -n --map-user): %s" % detail)
        sys.exit(1)
    failures, tmps = [], []

    tmp = make_root(read_only=True)
    tmps.append(tmp)
    rc, out = run(tmp)
    mirror = os.path.join(tmp, "home", ".claude", "skills")
    named = [n for n in ("alpha", "beta", "gone") if os.path.join(mirror, n) in out.split("FAILED", 1)[-1]]
    codex = links(tmp, ".codex")
    if rc != 1 or "Traceback" in out or codex != sorted(SKILLS) or named != ["alpha", "beta", "gone"]:
        failures.append("read-only mirror: exit %d, Traceback %s, codex links %s, named %s: %s" % (
            rc, "Traceback" in out, codex, named, tail(out, 2)))
    if not gamma_intact(tmp):
        failures.append("read-only mirror: the real dir gamma was removed or replaced")

    # Control: the same layout, writable, is fully repaired and exits 0 -- the gamma block
    # alone is reported, not failed.
    tmp = make_root(read_only=False)
    tmps.append(tmp)
    rc, out = run(tmp)
    got = links(tmp, ".claude")
    gone = os.path.lexists(os.path.join(tmp, "home", ".claude", "skills", "gone"))
    if rc or got != ["alpha", "beta", "delta"] or gone or "BLOCKED" not in out or not gamma_intact(tmp):
        failures.append("control: writable mirror: exit %d, links %s, dangling kept %s, gamma intact %s: %s"
                        % (rc, got, gone, gamma_intact(tmp), tail(out, 2)))

    # $CODEX_HOME relocates ~/.codex (Codex's own convention, lib.CODEX_HOME): the second mirror
    # goes there, and no ~/.codex is made.
    tmp = make_root(read_only=False, codex=False)
    tmps.append(tmp)
    ch = os.path.join(tmp, "ch")
    rc, out = run(tmp, CODEX_HOME=ch)
    got = links(tmp, ch) if os.path.isdir(os.path.join(ch, "skills")) else None
    home_codex = os.path.lexists(os.path.join(tmp, "home", ".codex"))
    if rc or got != sorted(SKILLS) or home_codex:
        failures.append("CODEX_HOME=<tmp>/ch: exit %d, $CODEX_HOME/skills links %s, ~/.codex created %s: %s"
                        % (rc, got, home_codex, tail(out, 2)))

    # A dangling link whose name is a current skill, beside a dangling one that is not: the apply
    # repoints alpha and prunes gone, 4 + 4 linked and 1 pruned.
    tmp = bare_root()
    tmps.append(tmp)
    mirror = os.path.join(tmp, "home", ".claude", "skills")
    os.makedirs(mirror)
    os.makedirs(os.path.join(tmp, "home", ".codex", "skills"))
    os.symlink(os.path.join(tmp, "nonexistent-alpha"), os.path.join(mirror, "alpha"))
    os.symlink(os.path.join(tmp, "nonexistent"), os.path.join(mirror, "gone"))
    parity("dangling link named alpha", tmp, failures)
    if links(tmp, ".claude") != sorted(SKILLS) or os.path.lexists(os.path.join(mirror, "gone")):
        failures.append("dangling link named alpha: after the apply links %s, gone kept %s"
                        % (links(tmp, ".claude"), os.path.lexists(os.path.join(mirror, "gone"))))

    # A fresh HOME: the dry-run counts every link the apply makes, 4 per mirror, and creates nothing.
    tmp = bare_root()
    tmps.append(tmp)
    rc_dry, dry = run(tmp, "--dry-run")
    made = [m for m in (".claude", ".codex") if os.path.lexists(os.path.join(tmp, "home", m))]
    rc, out = run(tmp)
    if rc_dry or rc or counts(dry) != counts(out) or counts(out) != (8, 0) or made:
        failures.append("dry-run vs apply, fresh HOME: dry %s, apply %s, the dry-run created %s: %s | %s"
                        % (counts(dry), counts(out), made, tail(dry, 1), tail(out, 1)))

    # ~/.codex/skills is a regular file: the apply cannot make that mirror and says so, exit 1, and
    # the dry-run says the same instead of counting links under a file.
    tmp = bare_root()
    tmps.append(tmp)
    blocker = os.path.join(tmp, "home", ".codex", "skills")
    os.makedirs(os.path.dirname(blocker))
    with open(blocker, "w") as f:
        f.write("not a directory\n")
    rc_dry, dry = run(tmp, "--dry-run")
    rc, out = run(tmp)
    named = [blocker in o.split("FAILED", 1)[-1] and "FAILED" in o for o in (dry, out)]
    if (rc_dry, counts(dry), named[0]) != (rc, counts(out), named[1]) or rc != 1 or not named[1]:
        failures.append("dry-run vs apply, a mirror that is a file: dry exit %d, %s, named %s, apply exit %d, %s, "
                        "named %s: %s | %s" % (rc_dry, counts(dry), named[0], rc, counts(out), named[1],
                                               tail(dry, 1), tail(out, 1)))

    failures += RULE
    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 7 cases" % len(failures))
    for t in tmps:  # writable again, so a kept dir can be removed too
        m = os.path.join(t, "home", ".claude", "skills")
        if os.path.isdir(m):
            os.chmod(m, os.stat(m).st_mode | stat.S_IWUSR)
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
