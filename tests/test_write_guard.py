#!/usr/bin/env python3
"""A plain copy of forge writes nothing, however its scripts are run. Once,
two test agents copied forge to /tmp and ran scripts from the copies. The copies still held the
real profiles, so sync_system_doc.py --apply rewrote CLAUDE.md pointers and AGENT-SYSTEM.md in
~20 real projects with the copy's path, and register_project.py, whose ROOT was hardcoded to
master, wrote a profile and an EXTRAS row into master. The worktree guard did not fire: a copy
is not a linked worktree.

This copies the tracked files into a temp dir (not a worktree), points every profile at a
throwaway project so a broken guard can only write inside the temp dir, and runs the scripts
with a temp HOME whose settings.json names another checkout as the installed one. Each refused
run must leave the whole temp dir byte-identical, and the real checkouts must not gain the
probe project. Each has a positive run beside it, the same command with the copy named as
installed, that does write -- so none can pass by writing nothing anywhere.

register_project.py is first run dry: its plan must name the copy's own profile path. If it
names any other checkout, no write case runs at all, because it would write there.

Every script runs in an empty network namespace with a PATH whose systemctl only logs: if the
guard broke, register_project --apply would start the copy's sync_agent_config.py, which can
reach for the host's systemd and network.

Seen failing on 3c8f6a2: sync_system_doc.py --apply from the copy "wrote
['projects/forge', 'projects/forge/.claude', 'projects/forge/.claude/AGENT-SYSTEM.md', ...]",
register_project.py's dry-run "plans its profile at ['/home/user/dev/Projects/forge/config/
profiles/guard-probe.claude.json']" (so no write case ran), and sync_skill_keep.py --apply "wrote
['forge/config/profiles/app.claude.json', ...]: 18 profile(s) updated". With ROOT derived but
its guard removed, register_project.py --apply-fs "exit 0 (want 1), no refusal message, wrote
['forge/config/profiles/guard-probe.claude.json', 'forge/scripts/sync/sync_skill_keep.py',
'projects/guard-probe', ...]". The two tripwires, seen firing the same day: with the copy counted as a
real checkout, "/tmp/forge-guard-.../forge gained the probe project 'guard-probe'"; with lib's
copy check removed, register_project --apply ran the copy's sync_agent_config.py and "systemctl
was called: ['--user daemon-reload', ...]" -- the stub,
in the empty namespace. refused() asserts the whole refusal, "; apply from <installed>" included:
with lib printing the older text, "sync_system_doc.py --apply from a copy: exit 0 (want 0), no
refusal message, wrote []".

The incident itself is a second copy that keeps the real profiles, run with HOME set to a scratch
dir that names no checkout. It runs under `unshare -rmn` with an empty tmpfs mounted over every
real project tree and checked before the command starts. Its positive control is the same run
with HOME set to the namespace's own home, which is also tmpfs-covered and counts as a fresh
machine. Before the sandbox-HOME rule, on it "wrote ['/home/user/dev/.claude',
'/home/user/dev/.claude/AGENT-SYSTEM.md', '/home/user/dev/AGENTS.md',
'/home/user/dev/CLAUDE.md', ...]: 54 change(s) applied". All of it landed in the tmpfs, and
`find -newer` found no real file touched."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
from sandbox import FORGE, git, tail  # noqa: E402

NAME = "guard-probe"
# register_project.py is a private skill: a checkout that has skills/new-project runs the cases that use it, and
# without it they are NOT RUN. The rest of the world is the engine files and tests/fixtures/config.
REGISTER = "skills/new-project/scripts/register_project.py"
HAVE_REGISTER = os.path.exists(os.path.join(FORGE, REGISTER))
# Runs inside `unshare -rmn`: an empty tmpfs over every real project tree (and over the namespace's
# own pw_dir for the positive control), verified before anything runs, then the command, then
# what changed under those mounts. The mounts die with the namespace, so a broken guard writes
# into memory that no one else can see.
DRIVER = r"""
import hashlib, json, os, pwd, subprocess, sys
spec = json.loads(sys.argv[1])
tops = spec["tops"] + ([pwd.getpwuid(os.getuid()).pw_dir] if spec["real_home"] else [])
for t in tops:
    subprocess.run(["mount", "-t", "tmpfs", "forge-guard", t], check=True)
    with open("/proc/self/mounts") as f:
        if not any(l.split()[1:3] == [t, "tmpfs"] for l in f) or os.listdir(t):
            sys.exit("no empty tmpfs on %s -- refusing to run" % t)
for p in spec["projects"]:
    os.makedirs(p, exist_ok=True)
def snap():
    out = {}
    for t in tops:
        for d, dirs, files in os.walk(t):
            for n in dirs + files:
                p = os.path.join(d, n)
                st = os.lstat(p)
                body = open(p, "rb").read() if os.path.isfile(p) and not os.path.islink(p) else b""
                out[p] = [st.st_mode, st.st_mtime_ns, hashlib.sha256(body).hexdigest()]
    return out
env = dict(spec["env"], HOME=tops[-1]) if spec["real_home"] else spec["env"]
before = snap()
r = subprocess.run(spec["cmd"], cwd=spec["cwd"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
after = snap()
print(json.dumps({"rc": r.returncode, "out": r.stdout,
                  "moved": sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))}))
"""


def real_checkouts():
    """This checkout and the main checkout of its repository: where a hardcoded ROOT would write."""
    common = git(FORGE, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return sorted({FORGE, os.path.dirname(os.path.realpath(common))})


def main():
    tmp = sandbox.mkdtemp("forge-guard-")
    copy, projects, home, other = (os.path.join(tmp, d) for d in ("forge", "projects", "home", "installed"))
    stub, log = os.path.join(tmp, "bin"), os.path.join(tmp, "systemctl.log")
    failures = []

    # The copy is the engine files plus the fixtures, never this machine's profiles and skills: a copy_engine copy
    # has neither. Red there before, M1: "FileNotFoundError: .../config/forge.json" at test_write_guard.py:242
    # (the append of the probe check), and `os.listdir(.../skills)`-style reads once forge.json was seeded.
    sandbox.copy_engine(copy)
    sandbox.seed(copy)
    for skill in ("gsd-fast", "toy-common"):  # the toy skills the keep tables and the HOME mirror below name
        os.makedirs(os.path.join(copy, "skills", skill))
        with open(os.path.join(copy, "skills", skill, "SKILL.md"), "w") as f:
            f.write("---\nname: %s\ndescription: stub\n---\n" % skill)
    if HAVE_REGISTER:
        files = sandbox.ls_files("--", "skills/new-project")
        sandbox._copy_files([f for f in files if f], copy, set())
    incident = os.path.join(tmp, "incident", "forge")  # a second copy whose profiles name projects outside its world
    shutil.copytree(copy, incident, symlinks=True)
    # Its profiles name trees outside the world (tmp/incident/), the way the incident's real ones did. They are
    # toy trees made here, because the namespace mounts a tmpfs over each and a mount point must exist.
    for p in sorted(glob.glob(os.path.join(incident, "config", "profiles", "*.claude.json"))):
        name = os.path.basename(p)[:-len(".claude.json")]
        with open(p, encoding="utf-8") as f:
            prof = json.load(f)
        prof["project_path"] = os.path.join(tmp, "realish", name)
        os.makedirs(prof["project_path"])
        with open(p, "w", encoding="utf-8") as f:
            json.dump(prof, f, indent=2)
    for p in sorted(glob.glob(os.path.join(copy, "config", "profiles", "*.claude.json"))):
        name = os.path.basename(p)[:-len(".claude.json")]
        with open(p, encoding="utf-8") as f:
            prof = json.load(f)
        prof["project_path"] = os.path.join(projects, name)
        if name == "app":  # stale: sync_skill_keep.py --apply puts the gsd-* baseline back
            prof["skills_keep"] = [k for k in prof["skills_keep"] if not k.startswith("gsd-")]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(prof, f, indent=2)
    for name in ("forge", "app"):  # the other profiles' dirs are missing: skipped, never created
        os.makedirs(os.path.join(projects, name))
        git(os.path.join(projects, name), "init", "-q")
        with open(os.path.join(projects, name, "CLAUDE.md"), "w") as f:
            f.write("# %s\n" % name)
    os.makedirs(os.path.join(home, ".claude", "skills"))
    for d in sorted(glob.glob(os.path.join(copy, "skills", "*", ""))):  # the mirror relink_skills.py keeps
        os.symlink(d.rstrip("/"), os.path.join(home, ".claude", "skills", os.path.basename(d.rstrip("/"))))
    os.makedirs(os.path.join(home, ".claude", "skills", "omarchy"))  # standalone there, not in forge
    os.makedirs(os.path.join(other, "bin"))
    open(os.path.join(other, "bin", "forge"), "w").close()
    sandbox.stub_systemctl(stub, log)
    install = lambda root: sandbox.installed_settings(home, root)
    env = sandbox.bare_env(home, tmp, stub)  # no bytecode written into the copy either

    def run(script, *args):
        r = subprocess.run(["unshare", "-rn", sys.executable, os.path.join(copy, script)] + list(args),
                           cwd=copy, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
        return r.returncode, r.stdout

    def refused(label, script, *args, code=0):
        """The run exits `code`, says why, and writes not a byte in the temp dir."""
        before = sandbox.manifest(tmp, skip={log})
        rc, out = run(script, *args)
        after = sandbox.manifest(tmp, skip={log})
        moved = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        msg = "forge: %s is not the checkout this machine runs (%s) -- nothing written; apply from %s" % (
            copy, other, other)
        if rc != code or msg not in out or moved:
            failures.append("%s: exit %d (want %d), %s, wrote %s: %s" % (
                label, rc, code, "said why" if msg in out else "no refusal message", moved[:8],
                tail(out)))

    ok, detail = sandbox.unshare_ok()
    if not ok:
        print("FAIL no empty network namespace (unshare -rn): %s" % detail)
        sandbox.cleanup(True)
        sys.exit(1)

    # The incident itself: a copy whose profiles name the real projects, run with HOME set to a
    # scratch dir that names no installed checkout. The real project trees are covered by tmpfs
    # mounts inside the namespace, so even with the guard gone nothing reaches the disk.
    real = []
    for p in sorted(glob.glob(os.path.join(incident, "config", "profiles", "*.claude.json"))):
        with open(p, encoding="utf-8") as f:
            pp = json.load(f).get("project_path")
        if pp:
            real.append(os.path.realpath(pp))
    tops = sorted(t for t in set(real) if not any(t.startswith(o + os.sep) for o in real))
    keep = [tmp, os.path.realpath(sys.executable), os.path.realpath(sys.prefix), tempfile.gettempdir()]
    unsafe = [t for t in tops if t == "/" or not os.path.isabs(t)
              or any(k == t or k.startswith(t + os.sep) for k in keep)]
    ihome = os.path.join(tmp, "incident", "home")
    os.makedirs(ihome)

    def covered(real_home):
        spec = {"tops": tops, "projects": real, "real_home": real_home, "cwd": incident,
                "env": dict(env, HOME=ihome), "cmd": [sys.executable, os.path.join(incident, "scripts", "sync",
                                                                                   "sync_system_doc.py"), "--apply"]}
        r = subprocess.run(["unshare", "-rmn", sys.executable, "-c", DRIVER, json.dumps(spec)],
                           capture_output=True, text=True, timeout=300)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"rc": r.returncode, "out": (r.stdout + r.stderr).strip()[-300:], "moved": None}

    if unsafe or not tops:
        failures.append("the incident case cannot cover the real project trees safely: tops %s, unsafe %s" % (tops, unsafe))
    else:
        got = covered(False)
        msg = "forge: HOME is a sandbox (%s) but profiles point outside it (" % ihome
        if got["moved"] != [] or msg not in got["out"] or "-- nothing written" not in got["out"]:
            failures.append("the incident (a copy with the real profiles, HOME a scratch dir): exit %s, wrote %s: %s"
                            % (got["rc"], (got["moved"] or [])[:6], tail(got["out"])))
        got = covered(True)  # the namespace's own home, empty: a fresh machine, which may write
        if not got["moved"]:
            failures.append("control: the incident copy with a real, empty HOME wrote nothing: %s"
                            % tail(got["out"]))

    doc = os.path.join(projects, "forge", ".claude", "AGENT-SYSTEM.md")
    install(other)
    refused("sync_system_doc.py --apply from a copy", "scripts/sync/sync_system_doc.py", "--apply")
    install(copy)
    rc, out = run("scripts/sync/sync_system_doc.py", "--apply")
    # Exit 1: every profile but forge's and app's names a directory left missing on purpose, and
    # each is a "! <dir> missing on disk -- skipping" line (forge/sync.py agent_config's exit rule,
    # which sync_system_doc.py keeps; it exited 0 before).
    if rc != 1 or not os.path.exists(doc):
        failures.append("control: sync_system_doc.py --apply with the copy installed did not write %s: %s"
                        % (doc, tail(out)))

    if HAVE_REGISTER:
        install(other)
        rc, out = run(REGISTER, "--name", NAME,
                      "--path", os.path.join(projects, NAME), "--no-git")
        plan = [l.split()[-1] for l in out.splitlines() if l.strip().startswith("- profile")]
        want = os.path.join(copy, "config", "profiles", NAME + ".claude.json")
        if rc or plan != [want]:
            failures.append("register_project.py dry-run from a copy plans its profile at %s, want %s -- "
                            "no write case run, it would write there" % (plan, want))
        else:
            for flag in ("--apply-fs", "--apply"):
                refused("register_project.py %s from a copy" % flag, REGISTER,
                        "--name", NAME, "--path", os.path.join(projects, NAME), "--no-git", flag, code=1)
            install(copy)
            rc, out = run(REGISTER, "--name", NAME,
                          "--path", os.path.join(projects, NAME), "--no-git", "--apply-fs")
            # The extras table moved from sync_skill_keep.py to config/forge.json skill_keep.extras (T3 of docs/portable-design.md).
            with open(os.path.join(copy, "config", "forge.json"), encoding="utf-8") as f:
                extras = '"%s.claude.json"' % NAME in f.read()
            if rc or not (os.path.exists(want) and extras and os.path.isdir(os.path.join(projects, NAME))):
                failures.append("control: register_project.py --apply-fs with the copy installed wrote profile %s, "
                                "EXTRAS row %s: %s" % (os.path.exists(want), extras, tail(out)))
    else:
        print("NOT RUN: register_project.py from a copy (four cases) -- no skills/new-project in this checkout")

    # sync_skill_keep.py had no guard at all; app's profile was seeded without its gsd-* skills.
    install(other)
    refused("sync_skill_keep.py --apply from a copy", "scripts/sync/sync_skill_keep.py", "--apply")
    install(copy)
    rc, out = run("scripts/sync/sync_skill_keep.py", "--apply")
    if rc or "0 profile(s) updated" in out:
        failures.append("control: sync_skill_keep.py --apply with the copy installed updated nothing: %s"
                        % tail(out))

    for root in real_checkouts():
        gained = os.path.exists(os.path.join(root, "config", "profiles", NAME + ".claude.json"))
        for rel in (("scripts", "sync", "sync_skill_keep.py"), ("config", "forge.json")):
            if os.path.exists(os.path.join(root, *rel)):  # a stranger's checkout has no config/forge.json
                with open(os.path.join(root, *rel), encoding="utf-8") as f:
                    gained = gained or NAME in f.read()
        if gained:
            failures.append("%s gained the probe project %r" % (root, NAME))
    if os.path.exists(log):
        with open(log) as f:
            failures.append("systemctl was called: %s" % f.read().split("\n")[:3])

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 11 cases" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
