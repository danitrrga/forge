#!/usr/bin/env python3
"""Cases for worktree_guard.py. Run: python3 hooks/test_worktree_guard.py (forge test runs it).

Copied from the downstream project's .claude/hooks/test_worktree_guard.py at 77d2255e and made neutral
(a research note on worktree guards, W1). It builds a
real repository in a temp folder, with two linked worktrees under .claude/worktrees/, and a toy
forge beside it: a copy of the hook under <toy>/hooks/ and toy profiles under
<toy>/config/profiles/, which the hook reads through `--project NAME`. Each PreToolUse payload
goes to the hook in a subprocess. A block case checks the exit code and the reason, so a case
blocked by the wrong rule fails too.

The fixture lives under /tmp, which the hook allows as scratch, so the suite points the
hook's scratch list at a folder of its own (WORKTREE_GUARD_SCRATCH). One case runs
without that override, to show the real /tmp is allowed. The write_roots cases judge
the real home's paths (~/wtguard-notes, ~/.cache/wtguard-*), which need not exist; the symlink
case needs a real link, so it runs with HOME set to a home folder inside the fixture.
CLAUDE_PROJECT_DIR names another repository on every call: the project root is the profile's
project_path, and a hook that read the variable would fail the placement cases.

The ALLOW half matters as much as the block half: a hook that blocks everything stops
every agent. The MAIN half reruns every write block from the main checkout and from a
folder in no repository, where only this repository's worktree placement is checked.

Controls that stay in the suite, each the opposite verdict on a case the main profile passes:
  * profile `bare` ("worktree_guard": true) refuses every write_roots allow and the
    worktree_dirs allow, so the parameters are seen to do something;
  * profile `elsewhere` (project_path is another repository) allows the placement blocks run
    from the main checkout, since those are no longer this project's worktrees;
  * an unusable profile (no file, not JSON, a wrong shape, no project_path, no --project) is
    refused inside a worktree and allowed in the main checkout.

  WORKTREE_GUARD_UNDER_TEST=<file>  run the cases against another copy of the hook
  --latency [N]                     time N calls (default 200) of an allow and a block
"""
import importlib.util
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get("WORKTREE_GUARD_UNDER_TEST") or os.path.join(HERE, "worktree_guard.py")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="wtguard-"))
MAIN = os.path.join(BASE, "main")
WT = os.path.join(MAIN, ".claude", "worktrees", "agent-a")
WT_B = os.path.join(MAIN, ".claude", "worktrees", "agent-b")
STRAY = os.path.join(BASE, "stray-wt")          # a worktree made outside .claude/worktrees
SCRATCH = os.path.join(BASE, "scratch")        # stands for /tmp
ELSEWHERE = os.path.join(BASE, "home")         # a folder in no repository, like ~/notes
NOREPO = os.path.join(BASE, "norepo")          # a cwd outside any repository
OTHER = os.path.join(BASE, "other")            # another project's repository
# Worktree folders whose `.git` file the guard cannot read: half-written, and not UTF-8.
HALF = os.path.join(MAIN, ".claude", "worktrees", "half-written")
NOT_UTF8 = os.path.join(MAIN, ".claude", "worktrees", "not-utf8")
BROKEN_ELSEWHERE = os.path.join(BASE, "broken-elsewhere")   # the same `.git` file, not in .claude/worktrees
# A home folder of the suite's own, passed to the hook as HOME, for the ~/.cache/wtguard-*/ cases
# that need a real symlink on disk.
FAKE_HOME = os.path.join(BASE, "fake-home")
ELP_X = os.path.join(FAKE_HOME, ".cache", "wtguard-x")
REAL_HOME = os.path.expanduser("~")
# The toy forge: the hook under test copied into <TOY>/hooks/, its profiles in <TOY>/config/profiles/.
TOY = os.path.join(BASE, "forge")
TOY_HOOK = os.path.join(TOY, "hooks", "worktree_guard.py")
PARKED = os.path.join(BASE, "parked")           # an extra worktree_dirs folder of profile `toy`
SV = os.path.join(BASE, "sv-")                  # a worktree_dirs prefix of profile `toy`, like GSD's /tmp/sv-
PROFILES = {
    # write_roots: a folder (the downstream project's shared notes) and a prefix (its ~/.cache/elp-<name>/).
    "toy": {"project_path": MAIN, "worktree_guard": {
        "write_roots": [{"path": "~/wtguard-notes", "why": "shared notes"},
                        {"prefix": "~/.cache/wtguard-", "why": "large output"}],
        "worktree_dirs": [{"path": PARKED, "why": "a long-lived copy"},
                          {"prefix": SV, "why": "GSD's code fixer, mktemp -d /tmp/sv-<phase>-reviewfix-XXXXXX"}]}},
    "bare": {"project_path": MAIN, "worktree_guard": True},
    "elsewhere": {"project_path": OTHER, "worktree_guard": True},
    # Guard off, its parameters declared (forge's own profile): the hook reads them alike.
    "off": {"project_path": MAIN, "worktree_guard": {"on": False, "worktree_dirs": [{"path": PARKED, "why": "w"}]}},
    "nopath": {"worktree_guard": True},
    "norepo": {"project_path": NOREPO, "worktree_guard": True},
    "wrongtype": {"project_path": MAIN, "worktree_guard": "yes"},
    "onnotbool": {"project_path": MAIN, "worktree_guard": {"on": "no"}},
    "notalist": {"project_path": MAIN, "worktree_guard": {"write_roots": {"path": "/x", "why": "w"}}},
    "nowhy": {"project_path": MAIN, "worktree_guard": {"write_roots": [{"path": "/x"}]}},
    "emptywhy": {"project_path": MAIN, "worktree_guard": {"write_roots": [{"path": "/x", "why": " "}]}},
    "dirbareprefix": {"project_path": MAIN, "worktree_guard": {"worktree_dirs": [{"prefix": "/tmp/", "why": "w"}]}},
    "dirboth": {"project_path": MAIN, "worktree_guard": {"worktree_dirs": [{"prefix": "/x", "path": "/y", "why": "w"}]}},
    "relative": {"project_path": MAIN, "worktree_guard": {"worktree_dirs": [{"path": "parked", "why": "w"}]}},
    "unknownkey": {"project_path": MAIN, "worktree_guard": {"write_root": []}},
    "bareprefix": {"project_path": MAIN, "worktree_guard": {"write_roots": [{"prefix": "~/.cache/", "why": "w"}]}},
}
# Arguments naming a profile the hook cannot use: refused inside a worktree, allowed outside.
UNREADABLE = [("--project", n) for n in (
    "nopath", "norepo", "wrongtype", "onnotbool", "notalist", "nowhy", "emptywhy", "dirbareprefix", "dirboth", "relative",
    "unknownkey", "bareprefix", "missing", "notjson", "../forge/config/profiles/toy")] + [(), ("--project",), ("--other", "toy")]


# lefthook runs this suite inside a git hook, which exports GIT_DIR and GIT_INDEX_FILE. In a
# linked worktree GIT_DIR is absolute, so a fixture `git init` or `git commit` inherited it
# and ran against the real repository: it set core.bare=true in the shared config, made
# commits on the branch being committed and registered the fixture worktrees (found on
# this file's first commit). The fixture's git sees no GIT_* variable at all.
GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(*args, cwd=MAIN):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                    *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV)


def build_fixture():
    for d in (MAIN, SCRATCH, ELSEWHERE, NOREPO, OTHER, PARKED, os.path.dirname(TOY_HOOK),
              os.path.join(TOY, "config", "profiles")):
        os.makedirs(d)
    shutil.copy(HOOK, TOY_HOOK)
    for name, prof in PROFILES.items():
        with open(os.path.join(TOY, "config", "profiles", name + ".claude.json"), "w") as fh:
            json.dump(dict(prof, project=name), fh)
    with open(os.path.join(TOY, "config", "profiles", "notjson.claude.json"), "w") as fh:
        fh.write("{nope")
    git("init", "-q")
    git("init", "-q", cwd=OTHER)
    with open(os.path.join(MAIN, "AGENTS.md"), "w") as fh:
        fh.write("x\n")
    git("add", "AGENTS.md")
    git("commit", "-qm", "init")
    git("worktree", "add", "-q", "-b", "agent-a", WT)
    git("worktree", "add", "-q", "-b", "agent-b", WT_B)
    # A renamed branch, as in the downstream project's own day-5 worktree: GSD Core's guard would
    # ignore it, because it is not agent-*.
    git("branch", "-m", "agent-a", "system/renamed", cwd=WT)
    git("worktree", "add", "-q", "-b", "stray", STRAY)
    # A symlink inside the worktree that points into the main checkout.
    os.symlink(MAIN, os.path.join(WT, "link-to-main"))
    os.makedirs(os.path.join(WT, "apps"))
    for d, body in ((HALF, b"gitd"), (NOT_UTF8, b"gitdir: \xff\xfe\n"), (BROKEN_ELSEWHERE, b"gitd")):
        os.makedirs(d)
        with open(os.path.join(d, ".git"), "wb") as fh:
            fh.write(body)
    # A symlink inside an allowed ~/.cache/wtguard-*/ folder that points out of it.
    os.makedirs(ELP_X)
    os.symlink(ELSEWHERE, os.path.join(ELP_X, "out"))


def run(tool, ti, cwd, env_extra=None, raw=None, args=("--project", "toy")):
    env = dict(os.environ, WORKTREE_GUARD_SCRATCH=SCRATCH, CLAUDE_PROJECT_DIR=OTHER)
    env.update(env_extra or {})
    for k, v in list(env.items()):
        if v is None:
            del env[k]
    payload = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": ti, "cwd": cwd})
    try:
        r = subprocess.run([sys.executable, TOY_HOOK, *args], input=payload, capture_output=True, text=True,
                           env=env, timeout=20)
    except subprocess.TimeoutExpired:
        return 124, "timed out after 20 s"
    return r.returncode, r.stderr


def bash(cmd):
    return ("Bash", {"command": cmd})


def write(p):
    return ("Write", {"file_path": p, "content": "x"})


# Writes that must be blocked from inside the worktree WT: (tool, input, reason).
WT_BLOCK = [
    write(os.path.join(MAIN, "apps", "x.ts")) + ("outside this worktree",),
    ("Edit", {"file_path": os.path.join(MAIN, "AGENTS.md"), "old_string": "x", "new_string": "y"}, "outside this worktree"),
    ("MultiEdit", {"file_path": os.path.join(MAIN, "AGENTS.md"), "edits": []}, "outside this worktree"),
    ("NotebookEdit", {"notebook_path": os.path.join(MAIN, "n.ipynb"), "new_source": "x"}, "outside this worktree"),
    write(os.path.join(WT_B, "x.ts")) + ("outside this worktree",),
    write(os.path.join(STRAY, "x.ts")) + ("outside this worktree",),
    write(os.path.join(MAIN, ".git", "worktrees", "agent-a", "HEAD")) + ("git metadata",),
    write(os.path.join(WT, ".git")) + ("git metadata",),
    write(os.path.join(WT, "apps", "..", "..", "agent-b", "x")) + ("outside this worktree",),
    write(os.path.join(WT, "link-to-main", "x.ts")) + ("outside this worktree",),
    write("../agent-b/x.ts") + ("outside this worktree",),
    write(os.path.join(ELSEWHERE, "notes.md")) + ("outside this worktree",),
    write("~/wtguard-probe.md") + ("outside this worktree",),
    # `~user/` is that user's home, as the shell reads it.
    write("~root/wtguard-probe.md") + ("resolves to /root/wtguard-probe.md",),
    bash("echo x > ~root/wtguard-probe") + ("resolves to /root/wtguard-probe",),
    ("Write", {"file_path": [], "content": "x"}, "not a path"),
    ("Edit", {"file_path": {"p": 1}}, "not a path"),
    bash("echo x > %s/f" % MAIN) + ("outside this worktree",),
    bash("echo x >> %s/f" % MAIN) + ("outside this worktree",),
    bash("echo x >'%s/f'" % MAIN) + ("outside this worktree",),
    bash("make 2> %s/err.log" % MAIN) + ("outside this worktree",),
    bash("make &> %s/all.log" % MAIN) + ("outside this worktree",),
    bash("cd %s && echo x > f" % MAIN) + ("outside this worktree",),
    bash("(cd %s && echo x > f)" % MAIN) + ("outside this worktree",),
    bash("cd .. && touch f") + ("outside this worktree",),
    bash("D=%s; echo x > $D/f" % MAIN) + ("outside this worktree",),
    bash("echo x > $HOME/wtguard-probe") + ("outside this worktree",),
    bash("echo x | tee %s/f" % MAIN) + ("outside this worktree",),
    bash("tee -a %s/f < a" % MAIN) + ("outside this worktree",),
    bash("cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("cp -r src %s" % MAIN) + ("outside this worktree",),
    bash("cp -t %s a b" % MAIN) + ("outside this worktree",),
    bash("cp --target-directory=%s a" % MAIN) + ("outside this worktree",),
    bash("mv %s/AGENTS.md ." % MAIN) + ("outside this worktree",),
    bash("mv a %s/" % WT_B) + ("outside this worktree",),
    bash("ln -s a %s/x" % MAIN) + ("outside this worktree",),
    bash("rsync -a src/ %s/" % MAIN) + ("outside this worktree",),
    bash("install -m 644 a %s/x" % MAIN) + ("outside this worktree",),
    bash("rm -rf %s/apps" % MAIN) + ("outside this worktree",),
    bash("touch %s/x" % MAIN) + ("outside this worktree",),
    bash("mkdir -p %s/new" % MAIN) + ("outside this worktree",),
    bash("truncate -s 0 %s/AGENTS.md" % MAIN) + ("outside this worktree",),
    # The reference of touch -r / truncate -r is read, but the files it is given with are written
    # (round 10, wt-false-refusal): skipping the option's value must not skip a real target.
    bash("touch -r probe.txt %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("touch -r %s/AGENTS.md %s/new.txt" % (MAIN, MAIN)) + ("%s/new.txt resolves" % MAIN,),
    bash("touch --reference probe.txt %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("touch -d yesterday %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("truncate -r probe.txt %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("truncate --reference=probe.txt %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("truncate -s 10 %s/new.txt" % MAIN) + ("%s/new.txt resolves" % MAIN,),
    bash("sed -i 's/x/y/' %s/AGENTS.md" % MAIN) + ("outside this worktree",),
    bash("dd if=a of=%s/x" % MAIN) + ("outside this worktree",),
    bash("sh -c 'echo x > %s/f'" % MAIN) + ("outside this worktree",),
    bash("bash -c \"true; cp a %s/x\"" % MAIN) + ("outside this worktree",),
    bash("sudo tee %s/f" % MAIN) + ("outside this worktree",),
    bash("ls | xargs -I{} cp {} %s/" % MAIN) + ("outside this worktree",),
    # A wrapper with its own options before the writer (round 10 lead; the command guard has stepped
    # over these since 2bb8472). strip_prefix knew sudo, command, nohup, time, env and exec only
    # without options, so `timeout 5 rm F` was read as the command `timeout`.
    bash("timeout 5 rm %s/AGENTS.md" % MAIN) + ("outside this worktree",),
    bash("timeout --signal=KILL 5 touch %s/x" % MAIN) + ("outside this worktree",),
    bash("timeout -k 2 5 tee %s/f" % MAIN) + ("outside this worktree",),
    bash("nice tee %s/f" % MAIN) + ("outside this worktree",),
    bash("nice -n 5 cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("command -p cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("nohup cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("stdbuf -oL tee %s/f" % MAIN) + ("outside this worktree",),
    bash("env VAR=x cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("env -i PATH=/bin cp a %s/x" % MAIN) + ("outside this worktree",),
    bash("sudo -u root tee %s/f" % MAIN) + ("outside this worktree",),
    bash("ionice -c3 nice -n 5 timeout 9 mv a %s/x" % MAIN) + ("outside this worktree",),
    bash("timeout 5 sh -c 'echo x > %s/f'" % MAIN) + ("outside this worktree",),
    bash("nice -n 5 python3 -c \"open('%s/x','w')\"" % MAIN) + ("outside this worktree",),
    bash("timeout 5 python3 - <<'EOF'\nopen('%s/x', 'w')\nEOF" % MAIN) + ("outside this worktree",),
    bash("echo $(timeout 5 cp a %s/f)" % MAIN) + ("outside this worktree",),
    bash("echo 'gitdir: %s/.git' > .git" % MAIN) + ("git metadata",),
    bash("cat > %s/f <<'EOF'\nhello\nEOF" % MAIN) + ("outside this worktree",),
    bash("echo x > link-to-main/f") + ("outside this worktree",),
    bash("export D=%s; echo x > $D/f" % MAIN) + ("outside this worktree",),
    bash("S=%s; for f in a b; do echo x > $S/out_$f; done" % MAIN) + ("outside this worktree",),
    bash("rm -rf %s/apps 2>/dev/null" % MAIN) + ("outside this worktree",),
    bash("# don't touch it\necho x > %s/f" % MAIN) + ("outside this worktree",),
    # Writes the guard did not read until Codex ran them from a worktree (each "SHOULD
    # BLOCK but rc=0"): a download or unpack aimed outside, a write inside a command substitution,
    # and an interpreter's inline code that writes a literal absolute path.
    bash("curl -o %s/escaped.txt https://x" % MAIN) + ("outside this worktree",),
    bash("curl -fsSLo %s/x https://x" % MAIN) + ("outside this worktree",),
    bash("curl --output=%s/x https://x" % MAIN) + ("outside this worktree",),
    bash("curl -sS https://x --output %s/x" % MAIN) + ("outside this worktree",),
    bash("cd %s && curl -LO https://x/f.tgz" % MAIN) + ("outside this worktree",),
    bash("curl -O --output-dir %s https://x/f.tgz" % MAIN) + ("outside this worktree",),
    bash("wget -O %s/x https://x" % MAIN) + ("outside this worktree",),
    bash("wget -qO%s/x https://x" % MAIN) + ("outside this worktree",),
    bash("wget -P %s https://x/f" % MAIN) + ("outside this worktree",),
    bash("cd %s && wget -q https://x/f" % MAIN) + ("outside this worktree",),
    bash("tar -C %s -xf archive.tar" % MAIN) + ("outside this worktree",),
    bash("tar xzf a.tgz --directory=%s" % MAIN) + ("outside this worktree",),
    bash("tar -xzf a.tgz -C%s" % MAIN) + ("outside this worktree",),
    bash("tar -czf %s/out.tgz src" % MAIN) + ("outside this worktree",),
    bash("tar czf %s/out.tgz src" % MAIN) + ("outside this worktree",),
    bash("cd %s && tar -xf /x/a.tar" % MAIN) + ("outside this worktree",),
    bash("unzip a.zip -d %s" % MAIN) + ("outside this worktree",),
    bash("unzip -o -d%s a.zip" % MAIN) + ("outside this worktree",),
    bash("cd %s && unzip -q a.zip" % MAIN) + ("outside this worktree",),
    bash("echo \"$(echo x > %s/f)\"" % MAIN) + ("outside this worktree",),
    bash("x=$(cp a %s/f)" % MAIN) + ("outside this worktree",),
    bash("y=\"$(tee %s/f < a)\"" % MAIN) + ("outside this worktree",),
    bash("echo `cp a %s/f`" % MAIN) + ("outside this worktree",),
    bash("make > >(tee %s/build.log)" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"open('%s/escaped.txt','w').write('x')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"open('%s/x', mode='a').write('x')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"import os; open(os.path.join('%s', 'x'), 'w')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"import pathlib; pathlib.Path('%s/x').write_text('y')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"import shutil; shutil.copy('a', '%s/x')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"import os; os.rename('%s/AGENTS.md', 'b')\"" % MAIN) + ("outside this worktree",),
    bash("python3 -c \"import shutil; shutil.rmtree('%s/apps')\"" % MAIN) + ("outside this worktree",),
    bash("python3 - <<'EOF'\nwith open('%s/x', 'a') as fh:\n    fh.write('y')\nEOF" % MAIN) + ("outside this worktree",),
    bash("node -e \"require('fs').writeFileSync('%s/x', 'y')\"" % MAIN) + ("outside this worktree",),
    bash("node -e \"const fs=require('fs'); fs.mkdirSync('%s/new', {recursive: true})\"" % MAIN) + ("outside this worktree",),
    bash("perl -e 'open(my $f, \">\", \"%s/x\"); print $f 1'" % MAIN) + ("outside this worktree",),
    bash("perl -e 'open(F, \">>%s/x\")'" % MAIN) + ("outside this worktree",),
    bash("ruby -e \"File.write('%s/x', 'y')\"" % MAIN) + ("outside this worktree",),
    bash("sh -c \"python3 -c \\\"open('%s/x','w')\\\"\"" % MAIN) + ("outside this worktree",),
    # Claude's memory folder stays blocked; a write_roots folder is that folder only.
    write(os.path.join(os.path.expanduser("~"), ".claude", "projects", "-p", "memory", "m.md")) + ("outside this worktree",),
    bash("cat > ~/.claude/projects/-p/memory/MEMORY.md <<'EOF'\nx\nEOF") + ("outside this worktree",),
    write(os.path.join(os.path.expanduser("~"), "wtguard-notes-old", "x.md")) + ("outside this worktree",),
    bash("echo x > ~/wtguard-notes.bak") + ("outside this worktree",),
    # Only ~/.cache/wtguard-*/ is writable in ~/.cache, judged on the resolved path.
    write(os.path.join(REAL_HOME, ".cache", "other", "x.log")) + ("outside this worktree",),
    bash("echo x > ~/.cache/other/x.log") + ("outside this worktree",),
    write(os.path.join(REAL_HOME, ".cache", "wtguard-ci", "..", "other", "x.log")) + ("outside this worktree",),
    write(os.path.join(REAL_HOME, ".cache", "wtguardx", "x.log")) + ("outside this worktree",),
    write(os.path.join(REAL_HOME, ".cache", "wtguard-", "x.log")) + ("outside this worktree",),
]

# Worktree placement of this repository, blocked from a worktree and from the main checkout.
LOCATION_BLOCK = [
    ("git worktree add ../../../elsewhere", "Worktrees of this project live only"),
    ("git worktree add -b feat %s/wt" % BASE, "Worktrees of this project live only"),
    ("git -C %s worktree add ../x" % MAIN, "Worktrees of this project live only"),
    ("git worktree add %s/.claude/worktrees/agent-a/.claude/worktrees/nested" % MAIN, "Worktrees of this project live only"),
    ("git worktree move %s %s/moved" % (WT_B, BASE), "Worktrees of this project live only"),
    ("sh -c 'git worktree add /opt/wt'", "Worktrees of this project live only"),
    # mktemp -d is resolved where the worktree goes (the downstream project's review, s80): a
    # template, -p DIR, --tmpdir=DIR, inline in the target, and `wt="$(...)"` quoted, which was
    # read as the literal folder <cwd>/$(mktemp -d ...) and blocked for that wrong path.
    ("wt=$(mktemp -d /opt/wt-XXXXXX) && git worktree add \"$wt\" -b mk", "worktree at /opt/wt-XXXXXX"),
    ("wt=\"$(mktemp -d -p /opt sv-XXXXXX)\"; git worktree add \"$wt\"", "worktree at /opt/sv-XXXXXX"),
    ("git worktree add \"$(mktemp -d --tmpdir=/opt)\" -b mk", "worktree at /opt/tmp.XXXXXXXXXX"),
    ("git worktree add `mktemp -d -p /opt`", "worktree at /opt/tmp.XXXXXXXXXX"),
    # A target it cannot resolve is refused, not let through (`wt=$(mktemp -d)` once passed
    # unchecked because the assignment, two words to shlex, was never recorded).
    ("git worktree add \"$WTGUARD_NEVER_SET\" -b x", "cannot tell where"),
    ("wt=$(cat .next-wt) && git worktree add \"$wt\"", "cannot tell where"),
    ("wt=$(git rev-parse --show-toplevel)-x; git worktree add \"$wt\"", "cannot tell where"),
    ("git worktree add \"$(pick-a-dir)/wt\"", "cannot tell where"),
    ("git worktree add \"%s/$WTGUARD_NEVER_SET/wt\"" % PARKED, "cannot tell where"),
    # An unreadable -C (a command's output, a variable set outside the command) is judged against
    # the cwd's repository, which is this project's here; a literal -C of another repository stays
    # allowed (LOCATION_ALLOW, and the OTHER cases in cases()). Round 10: each was let through.
    ("git -C \"$(git rev-parse --show-toplevel)\" worktree add /opt/x -b p", "Worktrees of this project live only"),
    ("git -C \"$WTGUARD_NEVER_SET\" worktree add /opt/x -b p", "Worktrees of this project live only"),
    ("git -C $WTGUARD_NEVER_SET worktree add /opt/x", "Worktrees of this project live only"),
    ("P=%s bash -c 'git -C $P worktree add /opt/x'" % MAIN, "Worktrees of this project live only"),
    ("git -C `cat .repo` worktree move %s /opt/x" % WT_B, "Worktrees of this project live only"),
    # A placement inside a command substitution, backticks or a double-quoted one is read like the
    # bare command (only nested shells were).
    ("echo $(git worktree add /opt/x)", "Worktrees of this project live only"),
    ("echo `git worktree add /opt/x`", "Worktrees of this project live only"),
    ("x=$(git worktree add /opt/x)", "Worktrees of this project live only"),
    ("echo \"$(git worktree add /opt/x)\"", "Worktrees of this project live only"),
    ("echo $(echo $(git worktree add /opt/x))", "Worktrees of this project live only"),
    ("cat <(git worktree add /opt/x)", "Worktrees of this project live only"),
    # A command's output in the last name may hold `/` or `..` (`$(printf ../../x)`, a branch
    # `feature/x`), so the name is not known to be one folder: refused. A bare $VAR is still
    # judged as the one name it is when unset or known (LOCATION_ALLOW).
    ("git worktree add \"%s/$(printf '../../../evil')\"" % os.path.join(MAIN, ".claude", "worktrees"), "cannot tell where"),
    ("git worktree add %s/agent-`git branch --show-current`" % os.path.join(MAIN, ".claude", "worktrees"), "cannot tell where"),
    ("git worktree add %ssvx-$(printf 'x/../../evil')" % SV, "cannot tell where"),
    # A wrapper in front of the git call hides nothing (round 10 lead).
    ("timeout 5 git worktree add /opt/x", "Worktrees of this project live only"),
    ("nice -n 5 git worktree add /opt/x", "Worktrees of this project live only"),
    ("env GIT_TRACE=1 git -C %s worktree add /opt/x" % MAIN, "Worktrees of this project live only"),
    ("sudo -u root git worktree add /opt/x", "Worktrees of this project live only"),
    ("command -p git worktree add /opt/x", "Worktrees of this project live only"),
    # A prefix folder is the worktree itself: <prefix><name>, never deeper, never the bare prefix.
    ("git worktree add %s01/deeper -b d" % SV, "Worktrees of this project live only"),
    ("git worktree add %s/x -b d" % SV, "Worktrees of this project live only"),
    ("git worktree add %s/svx-1 -b d" % BASE, "Worktrees of this project live only"),
]
# The same mktemp shapes landing where profile `toy` allows them: directly under PARKED, as a
# prefix folder SV<name>, or under .claude/worktrees; refused under profile `bare`, which has no
# PARKED and no prefix (the .claude/worktrees one stays allowed there).
LOCATION_ALLOW = [
    ("wt=$(mktemp -d -p %s wt-XXXXXX) && git worktree add \"$wt\" -b mk1" % PARKED, True),
    # GSD's code fixer, its two lines as written (gsd-code-fixer.md), padded_phase unset here.
    ("wt=$(mktemp -d \"%s${padded_phase}-reviewfix-XXXXXX\")\ngit worktree add -b \"$reviewfix_branch\" \"$wt\" \"$branch\"" % SV, True),
    ("wt=$(mktemp -d \"%s01-reviewfix-XXXXXX\")\ngit worktree add -b gsd-reviewfix/01-1 \"$wt\" main" % SV, True),
    ("git worktree add %s02-fix -b sv2" % SV, True),
    ("cd %s && wt=$(mktemp -d agent-XXXX) && git worktree add \"$wt\"" % os.path.join(MAIN, ".claude", "worktrees"), False),
    ("D=%s; git worktree add \"$D/agent-e\" -b e" % os.path.join(MAIN, ".claude", "worktrees"), False),
    # Unknown in the last name only: the folder is known, and judged.
    ("git worktree add \"%s/agent-$WTGUARD_NEVER_SET\"" % os.path.join(MAIN, ".claude", "worktrees"), False),
]

# worktree_dirs: profile `toy` adds PARKED, so a worktree may go directly under it, never deeper.
PARKED_ALLOW = "git worktree add %s/wt1 -b parked1" % PARKED
PARKED_BLOCK = "git worktree add %s/deeper/wt2" % PARKED

# From inside the worktree, these must pass.
WT_ALLOW = [
    write(os.path.join(WT, "apps", "x.ts")),
    write("apps/new/x.ts"),
    ("Edit", {"file_path": os.path.join(WT, "AGENTS.md"), "old_string": "x", "new_string": "y"}),
    ("NotebookEdit", {"notebook_path": os.path.join(WT, "n.ipynb"), "new_source": "x"}),
    write(os.path.join(WT, ".claude", "hooks", "x.py")),
    write(os.path.join(SCRATCH, "notes.md")),
    ("Write", {"content": "x"}),
    ("Read", {"file_path": os.path.join(MAIN, "AGENTS.md")}),
    ("Grep", {"pattern": "x", "path": MAIN}),
    ("Glob", {"pattern": "**/*", "path": ELSEWHERE}),
    ("mcp__x__y", {"file_path": os.path.join(MAIN, "f")}),
    bash("echo x > f"),
    bash("echo x > %s/f" % WT),
    bash("echo x > %s/out.txt" % SCRATCH),
    bash("cd %s && echo x > f" % SCRATCH),
    bash("ls %s; cat %s/AGENTS.md" % (MAIN, MAIN)),
    bash("grep -rn x %s > %s/hits" % (MAIN, SCRATCH)),
    bash("make 2>/dev/null >/dev/stderr"),
    bash("echo x >&2"),
    bash("cmd 2>&1 | tee build.log"),
    bash("cp %s/AGENTS.md ." % MAIN),
    bash("cp %s/AGENTS.md %s/" % (MAIN, SCRATCH)),
    bash("mv a b && rm -rf node_modules/.cache"),
    bash("git diff > %s/d.patch" % SCRATCH),
    bash("git status && git log --oneline -3"),
    bash("git worktree list"),
    bash("echo \"see a > %s/x\"" % MAIN),
    bash("git commit -m \"fix: x > %s/y is refused\"" % MAIN),
    # A quoted reply line in a commit message heredoc is data, not a redirect.
    bash("git commit -F - <<'EOF'\nfix: the note\n> %s/y was the old path\nEOF" % MAIN),
    bash("[ -f %s/AGENTS.md ] && echo yes" % MAIN),
    bash("sed 's/x/y/' %s/AGENTS.md > out" % MAIN),
    bash("git worktree add %s/.claude/worktrees/agent-c" % MAIN),
    # From inside a worktree, ../name is a sibling under .claude/worktrees.
    bash("git worktree add ../agent-d -b agent-d"),
    bash("cd %s && pnpm install" % WT),
    # Shapes the replay of recorded commands blocked before the parser was fixed.
    bash("awk '/<deferred>/{p=1} p{print} /<\\/deferred>/{p=0}' %s/AGENTS.md" % MAIN),
    bash("node -e \"const p=require('%s/package.json'); console.log(Object.keys(p).filter(k=>k))\"" % MAIN),
    bash("mkdir -p out 2>/dev/null; touch out/x 2> /dev/null"),
    # The reference file of touch and truncate is only read (round 10: "BLOCKED - shell write:
    # <ref> resolves to <ref>, outside this worktree" for `touch -r REF probe.txt`).
    # The twins of the wrapper blocks: the same wrappers on a write inside the worktree, or a read.
    bash("timeout 5 rm out"),
    bash("nice -n 5 tee out < %s/AGENTS.md" % MAIN),
    bash("command -p cp %s/AGENTS.md out" % MAIN),
    bash("env -i PATH=/bin cp %s/AGENTS.md out" % MAIN),
    bash("timeout 5 cat %s/AGENTS.md" % MAIN),
    bash("sudo -u root ls %s" % MAIN),
    bash("stdbuf -oL grep x %s/AGENTS.md" % MAIN),
    bash("nice -n 5 python3 -c \"open('%s/AGENTS.md').read()\"" % MAIN),
    bash("timeout 5 git worktree add ../agent-t -b agent-t"),
    bash("touch -r %s/AGENTS.md probe.txt" % MAIN),
    bash("touch -r%s/AGENTS.md probe.txt" % MAIN),
    bash("touch -ar %s/AGENTS.md probe.txt" % MAIN),
    bash("touch --reference=%s/AGENTS.md probe.txt" % MAIN),
    bash("touch --reference %s/AGENTS.md probe.txt" % MAIN),
    bash("touch -d yesterday -t 202001010000 probe.txt"),
    bash("truncate -r %s/AGENTS.md probe.txt" % MAIN),
    bash("truncate --reference %s/AGENTS.md probe.txt" % MAIN),
    bash("truncate --reference=%s/AGENTS.md probe.txt" % MAIN),
    bash("cd / && mkdir -p %s/x 2>/dev/null && rm -f %s/y 2> /dev/null" % (SCRATCH, SCRATCH)),
    bash("node -e \"const a=1; [a].filter(k=>/x/.test(k))\""),
    bash("export S=%s; echo x > $S/out" % SCRATCH),
    bash("S=%s; for f in a b; do echo x > $S/out_$f; done" % SCRATCH),
    bash("echo \"it's\" && echo x > f # don't > %s/f" % MAIN),
    # Another repository's worktrees follow that repository's rules.
    bash("git -C %s worktree add %s/other-wt" % (OTHER, SCRATCH)),
    # The twins of the download, unpack, substitution and interpreter blocks: the same shapes that
    # write inside the worktree, to stdout, or only read the main checkout.
    bash("curl -sSLo x https://x && curl -fsSL https://x -o out.tgz"),
    bash("curl -s https://x/%s/y | head" % MAIN),
    bash("curl -o - https://x && curl -LO https://x/f"),
    bash("wget -qO- https://x | head && wget -O - https://x"),
    bash("wget -q https://x/f && wget -P dl https://x/f"),
    bash("unzip a.zip && unzip -d out a.zip && unzip -l %s/a.zip" % MAIN),
    bash("tar -czf out.tgz -C %s src" % MAIN),
    bash("tar -xzf %s/a.tgz && tar -tzf %s/a.tgz" % (MAIN, MAIN)),
    bash("tar -C %s -cf - src | tar -xf -" % MAIN),
    bash("echo $((3 > 2)) && [ $(( a > b )) -eq 1 ]"),
    bash("echo \"$(git -C %s log -1 --format=%%H)\" > rev" % MAIN),
    bash("x=$(cat %s/AGENTS.md) && echo \"$x\" > out" % MAIN),
    bash("echo '$(echo x > %s/f)' && awk '{print $(NF)}' a" % MAIN),
    bash("git commit -m \"$(cat <<'EOF'\nfix: x > %s/y\nEOF\n)\"" % MAIN),
    bash("python3 -c \"d=open('%s/AGENTS.md').read(); open('out.txt','w').write(d)\"" % MAIN),
    bash("python3 -c \"import json; print(json.load(open('%s/x.json', 'r')))\"" % MAIN),
    bash("python3 -c \"open('%s/out.txt','w').write('x')\"" % WT),
    bash("python3 -c \"open('%s/out.txt','w').write('x')\"" % SCRATCH),
    bash("python3 -c \"import shutil; shutil.copy('%s/AGENTS.md', 'x')\"" % MAIN),
    bash("python3 -c \"import sys; sys.stdout.write('%s/x'); print(str(p).replace('%s', '%s'))\"" % (MAIN, WT, MAIN)),
    bash("python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['ls', '%s'])\nopen('out', 'w').write('x')\nEOF" % MAIN),
    bash("node -e \"require('fs').writeFileSync('out.json', JSON.stringify(require('%s/package.json')))\"" % MAIN),
    bash("node -e \"const fs=require('fs'); fs.copyFileSync('%s/AGENTS.md', 'x')\"" % MAIN),
    bash("perl -ne 'print if /x/' %s/AGENTS.md > out" % MAIN),
    # Shapes the replay of recorded worktree commands refused: a concatenated suffix.
    bash("python3 -c \"d='x'; open(d+'/ticket.yml','w').write('y')\""),
    bash("node -e \"require('fs').writeFileSync(require('os').homedir()+'/.cache/x', 'y')\""),
    bash("node -e \"require('fs').writeFileSync(require('path').join(__dirname, '/x'), 'y')\""),
    # Interpreter code quoted as prose (a commit message, an echo) is not run: the house style
    # quotes a finding's exact command in the commit body.
    bash("git commit -F - <<'EOF'\nfix: Codex ran python3 -c \"open('%s/x','w')\"\nEOF" % MAIN),
    bash("git commit -m \"fix: python3 -c \\\"open('%s/x','w')\\\" escaped\"" % MAIN),
    bash("echo 'node -e \"require(\\'fs\\').writeFileSync(\\'%s/x\\', 1)\"' > notes.md" % MAIN),
    bash("gh pr create --body \"python3 -c \\\"open('%s/x','w')\\\"\"" % MAIN),
    bash("git commit -m \"fix: python3 -c 'open(\\\"%s/x\\\", \\\"w\\\")' was let through\"" % MAIN),
    # `~` alone or `~/` is the home; `~name` is a relative file when no user is called so (Codex,
    # "SHOULD ALLOW but rc=2 (- ~notes.txt resolves to /home/<user>notes.txt, ...").
    write("~notes.txt"),
    bash("echo x > ~notes.txt"),
    bash("touch ~wtguard-no-such-user/x"),
]

# From inside the worktree, allowed by profile `toy`'s write_roots only, and refused under
# profile `bare`. Under the real HOME, as the real /tmp case is.
WRITE_ROOT_ALLOW = [
    write(os.path.join(os.path.expanduser("~"), "wtguard-notes", "PROGRESO.md")),
    bash("printf -- '- lane done\\n' >> ~/wtguard-notes/PROGRESO.md"),
    bash("cd ~/wtguard-notes && echo x > notes/day5.md"),
    write(os.path.join(REAL_HOME, ".cache", "wtguard-ci", "build.log")),
    bash("mkdir -p ~/.cache/wtguard-ci"),
    bash("pnpm build > ~/.cache/wtguard-ci/build.log 2>&1"),
    bash("echo x > $HOME/.cache/wtguard-walk/run-1/out.txt"),
]

MALFORMED = ["", "not json", "null", "[]", "42",
             json.dumps({"tool_name": "Write"}),
             json.dumps({"tool_name": "Write", "tool_input": "x", "cwd": WT}),
             json.dumps({"tool_name": "Bash", "tool_input": {"command": ["ls"]}, "cwd": WT}),
             json.dumps({"tool_name": "Bash", "tool_input": {"command": ""}, "cwd": WT}),
             json.dumps({"tool_input": {"file_path": "/etc/x"}, "cwd": WT})]

BARE = ("--project", "bare")


def cases():
    """(kind, tool, input, cwd, reason, env, hook arguments) or ("malformed", raw)."""
    out = []
    toy = ("--project", "toy")
    for tool, ti, why in WT_BLOCK:
        out.append(("block", tool, ti, WT, why, None, toy))
    for cmd, why in LOCATION_BLOCK:
        out.append(("block", "Bash", {"command": cmd}, WT, why, None, toy))
        # Enforced in the main checkout too, for this repository's worktrees only
        # (Portal, supervising session).
        out.append(("block", "Bash", {"command": cmd}, MAIN, why, None, toy))
        # Control: with project_path naming another repository, these are not this project's.
        out.append(("allow", "Bash", {"command": cmd}, MAIN, None, None, ("--project", "elsewhere")))
    for cmd, by_profile in LOCATION_ALLOW:
        for cwd in (WT, MAIN):
            out.append(("allow", "Bash", {"command": cmd}, cwd, None, None, toy))
            if by_profile:
                out.append(("block", "Bash", {"command": cmd}, cwd, "Worktrees of this project live only", None, BARE))
    # A bare mktemp -d lands in $TMPDIR (or /tmp): the hook reads the session's TMPDIR.
    out.append(("block", "Bash", {"command": "wt=$(mktemp -d) && git worktree add \"$wt\""}, MAIN,
                "worktree at %s/tmp.XXXXXXXXXX" % SCRATCH, {"TMPDIR": SCRATCH}, toy))
    # A variable this command sets from something unreadable hides the hook environment's value.
    out.append(("block", "Bash", {"command": "WTGUARD_WT=$(cat f); git worktree add \"$WTGUARD_WT\""}, MAIN,
                "cannot tell where", {"WTGUARD_WT": os.path.join(MAIN, ".claude", "worktrees", "agent-z")}, toy))
    out.append(("allow", "Bash", {"command": "git worktree add \"$WTGUARD_WT\""}, MAIN, None,
                {"WTGUARD_WT": os.path.join(MAIN, ".claude", "worktrees", "agent-z")}, toy))
    out.append(("allow", "Bash", {"command": "cd %s && git worktree add \"$(pwd)/agent-p\"" % os.path.join(
        MAIN, ".claude", "worktrees")}, MAIN, None, None, toy))
    # Another repository's target is not this project's, resolvable or not.
    out.append(("allow", "Bash", {"command": "git -C %s worktree add \"$WTGUARD_NEVER_SET\"" % OTHER}, MAIN, None, None, toy))
    for cwd in (WT, MAIN):
        out.append(("allow", "Bash", {"command": PARKED_ALLOW}, cwd, None, None, toy))
        out.append(("block", "Bash", {"command": PARKED_BLOCK}, cwd, "Worktrees of this project live only", None, toy))
        out.append(("block", "Bash", {"command": PARKED_ALLOW}, cwd, "Worktrees of this project live only", None, BARE))
        out.append(("allow", "Bash", {"command": PARKED_ALLOW}, cwd, None, None, ("--project", "off")))
    # A scratch repository makes its worktrees wherever it likes, from inside it, from the
    # main checkout and from a folder in no repository.
    # An unreadable -C from there is the scratch repository's own, or no repository's at all.
    for cmd, cwd in (("git -C \"$WTGUARD_NEVER_SET\" worktree add /opt/z", OTHER),
                     ("echo $(git worktree add /opt/z)", OTHER),
                     ("git -C \"$(cat .repo)\" worktree add /opt/z", NOREPO),
                     ("echo $(git -C %s worktree add %s/z)" % (OTHER, SCRATCH), MAIN),
                     ("echo $(git log -1) \"$(git rev-parse HEAD)\"", MAIN)):
        out.append(("allow", "Bash", {"command": cmd}, cwd, None, None, toy))
    for cmd, cwd in (("git worktree add /opt/wt", OTHER), ("git worktree add ../anywhere -b x", OTHER),
                     ("git -C %s worktree add %s/x" % (OTHER, SCRATCH), MAIN),
                     ("git -C %s worktree add /opt/y" % OTHER, NOREPO)):
        out.append(("allow", "Bash", {"command": cmd}, cwd, None, None, toy))
    # The worktree made outside .claude/worktrees is still a worktree: it is contained.
    out.append(("block", "Write", {"file_path": os.path.join(MAIN, "x")}, STRAY, "outside this worktree", None, toy))
    # The subdirectory of a worktree is the worktree.
    out.append(("block", "Write", {"file_path": os.path.join(MAIN, "x")}, os.path.join(WT, "apps"), "outside this worktree", None, toy))
    for tool, ti in WT_ALLOW:
        out.append(("allow", tool, ti, WT, None, None, toy))
    for tool, ti in WRITE_ROOT_ALLOW:
        out.append(("allow", tool, ti, WT, None, None, toy))
        out.append(("block", tool, ti, WT, "outside this worktree", None, BARE))
    # The real /tmp, with the suite's override removed.
    out.append(("allow", "Write", {"file_path": "/tmp/wtguard-real-tmp/x.md"}, WT, None, {"WORKTREE_GUARD_SCRATCH": None}, toy))
    out.append(("allow", "Bash", {"command": "echo x > /tmp/wtguard-real-tmp.txt"}, WT, None, {"WORKTREE_GUARD_SCRATCH": None}, toy))
    # ~/.cache/wtguard-*/ in the suite's own home. The plain write is the control that shows
    # this home works, so the symlink refusals below are the symlink's and not the home's.
    fake = {"HOME": FAKE_HOME}
    for tool, ti in (("Write", {"file_path": os.path.join(ELP_X, "f.log")}),
                     ("Bash", {"command": "echo x > ~/.cache/wtguard-x/f.log"})):
        out.append(("allow", tool, ti, WT, None, fake, toy))
        out.append(("block", tool, ti, WT, "outside this worktree", fake, BARE))
    out.append(("block", "Write", {"file_path": os.path.join(ELP_X, "out", "f.log")}, WT, "outside this worktree", fake, toy))
    out.append(("block", "Bash", {"command": "echo x > ~/.cache/wtguard-x/out/f.log"}, WT, "outside this worktree", fake, toy))
    # $PWD is the event's cwd, moved by a cd of the command, never the hook process's own PWD: a
    # subagent in a worktree runs hooks spawned from the main checkout (Codex: "SHOULD
    # ALLOW but rc=2 (- shell write: <main>/inside.txt resolves to <main>/inside.txt, ...").
    in_main = {"PWD": MAIN}
    for cmd in ('echo x > "$PWD/inside.txt"', "echo x > ${PWD}/inside.txt", "cp a $PWD/apps/"):
        out.append(("allow", "Bash", {"command": cmd}, WT, None, in_main, toy))
    for cmd in ('cd %s && echo x > "$PWD/f"' % MAIN, "cd .. && touch ${PWD}/f"):
        out.append(("block", "Bash", {"command": cmd}, WT, "outside this worktree", {"PWD": WT}, toy))
    # The main checkout and a cwd in no repository: every write block above is a no-op.
    for cwd in (MAIN, NOREPO):
        for tool, ti, why in WT_BLOCK:
            if tool == "Write" and not isinstance(ti.get("file_path"), str):
                continue
            out.append(("allow", tool, ti, cwd, None, None, toy))
    # The checkout cannot be read (Portal, review of PR #30, m1). Inside a .claude/worktrees/
    # folder that crash blocks, as the header promises; anywhere else it allows.
    target = os.path.join(MAIN, "apps", "x.ts")
    for cwd in (WT + "\u0000x", HALF, NOT_UTF8, os.path.join(HALF, "sub")):
        out.append(("block", "Write", {"file_path": target, "content": "x"}, cwd, "could not judge", None, toy))
    out.append(("block", "Bash", {"command": "echo x > %s" % target}, WT + "\u0000x", "could not judge", None, toy))
    for cwd in (MAIN + "\u0000x", NOREPO + "\u0000x", BROKEN_ELSEWHERE):
        out.append(("allow", "Write", {"file_path": target, "content": "x"}, cwd, None, None, toy))
        out.append(("allow", "Bash", {"command": "echo x > %s" % target}, cwd, None, None, toy))
    # A profile the hook cannot use: even a write inside the worktree is refused there, while the
    # main checkout goes on, its placement rule unread.
    for args in UNREADABLE:
        out.append(("block", "Write", {"file_path": os.path.join(WT, "x.ts"), "content": "x"}, WT,
                    "refused inside a worktree", None, args))
        out.append(("allow", "Write", {"file_path": os.path.join(MAIN, "x.ts"), "content": "x"}, MAIN, None, None, args))
        out.append(("allow", "Bash", {"command": "git worktree add /opt/wt"}, MAIN, None, None, args))
    for m in MALFORMED:
        out.append(("malformed", m))
    return out


def check(case):
    if case[0] == "malformed":
        rc, err = run(None, None, None, raw=case[1])
        return None if rc == 0 else "malformed payload %r: rc=%s %s" % (case[1][:50], rc, err.strip()[:120])
    kind, tool, ti, cwd, why, env_extra, args = case
    rc, err = run(tool, ti, cwd, env_extra, args=args)
    where = "main" if cwd == MAIN else "norepo" if cwd == NOREPO else "stray" if cwd == STRAY else "wt"
    label = "%s@%s [%s] %s" % (tool, where, " ".join(args), json.dumps(ti)[:110])
    if kind == "block":
        if rc != 2:
            return "SHOULD BLOCK but rc=%s: %s" % (rc, label)
        if why.lower() not in err.lower():
            return "blocked for the wrong reason (%s), wanted %r: %s" % (err.strip()[24:110], why, label)
    elif rc != 0:
        return "SHOULD ALLOW but rc=%s (%s): %s" % (rc, err.strip()[24:110], label)
    return None


def latency(n):
    allow = json.dumps({"tool_name": "Write", "tool_input": {"file_path": os.path.join(WT, "a.ts")}, "cwd": WT})
    block = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cd %s && echo x > f" % MAIN}, "cwd": WT})
    env = dict(os.environ, WORKTREE_GUARD_SCRATCH=SCRATCH)
    for name, raw in (("allow (Write in the worktree)", allow), ("block (cd main && redirect)", block)):
        times = []
        for _ in range(n):
            t = time.perf_counter()
            subprocess.run([sys.executable, TOY_HOOK, "--project", "toy"], input=raw, capture_output=True, text=True, env=env)
            times.append((time.perf_counter() - t) * 1000)
        times.sort()
        print("%s: median %.1f ms, p90 %.1f ms over %d calls" % (name, statistics.median(times), times[int(n * 0.9)], n))


# ------------------------------------------------------------------ scans that were quadratic
# Round 10 (wt-crash): three scans cost time quadratic in the command, so one ~100 KB command
# outran the hook's 10 s timeout. Before the fix, at 10,000 lines or words: drop_comments 13 s,
# `python ` x N through INLINE_CODE/HEREDOC_CODE 14 s, `python <<A` x N 11 s, a 40,000-letter name
# before `(` in inline code (_call_around) 17 s. What is checked here does not depend on the
# machine's speed, except the wall-time cases, whose limit is far above what the fixed code takes.

OLD_INTERP = r"(?:python3?|node|perl|ruby|deno|bun|php)"
# The patterns as they were before the fix, kept as the reference the new scans must agree with.
OLD_INLINE = re.compile(r"(?:^|[\s;&|(/])" + OLD_INTERP + r"\b[^\n'\"]*?\s-(?:c|e|p|pe|E|-eval)\s+(['\"])(.*?)(?<!\\)\1", re.S)
OLD_HEREDOC = re.compile(r"(?:^|[\s;&|(/])" + OLD_INTERP + r"\b[^\n]*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\s*(?:\n|$)", re.S)
FRAGMENTS = ["python", "python3", "node", "perl", " ", " ", " -c ", " -e ", " -p ", "--eval ", "'", '"', "<<A ", "<<-B ", "<<'E' ",
             "\n", "\n", "A\n", "B", "E\n", "x", "open('/x','w')", ";", "&&", "|", "(", "/", " -u ", "\\", "\\\"", "pythonx", "# c"]


def old_drop_comments(mod, text):
    spans, out, i = mod._quoted_spans(text), [], 0
    for m in re.finditer(r"(?:^|(?<=[\s;&|(]))#[^\n]*", text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        out.append(text[i:m.start()])
        i = m.end()
    return "".join(out) + text[i:]


class Counting(list):
    """A list that counts the items read from it, by index or by iteration."""
    reads = 0

    def __getitem__(self, i):
        Counting.reads += 1
        return list.__getitem__(self, i)

    def __iter__(self):
        for x in list.__iter__(self):
            Counting.reads += 1
            yield x


def scaling_checks():
    """Failure strings for the three scans: steps counted, the new scan equal to the old on a
    seeded corpus, then one generous wall-time case each through the hook itself."""
    spec = importlib.util.spec_from_file_location("wtguard_under_test", TOY_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fails = []
    # drop_comments reads each quoted span a bounded number of times, not once per comment.
    n = 2000
    text = "# c\necho 'x'\n" * n
    real_spans = mod._quoted_spans
    mod._quoted_spans = lambda t: Counting(real_spans(t))
    Counting.reads = 0
    got = mod.drop_comments(text)
    mod._quoted_spans = real_spans
    if got != "\necho 'x'\n" * n:
        fails.append("drop_comments changed its output on %d commented lines" % n)
    if Counting.reads > 8 * n:
        fails.append("drop_comments read the quoted spans %d times for %d comments and %d spans (limit %d): quadratic"
                     % (Counting.reads, n, n, 8 * n))
    # The new scans give what the old ones gave.
    rng = random.Random(10)
    corpus = ["".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(2, 14))) for _ in range(6000)]
    for t in corpus:
        old_i = [(m.group(1), m.group(2)) for m in OLD_INLINE.finditer(t)]
        new_i = [(m.group(1), m.group(2)) for m in mod.INLINE_CODE.finditer(t)]
        # Heredocs: the old regex also retried a second `<<` on the same line when the first had no
        # closing line, and a delimiter cut short (`<<Anode` closed by `A`). The new scan takes the
        # first operator and the whole word, as a shell does, so those two shapes are left out here.
        old_h = new_h = []
        if all(line.count("<<") <= 1 for line in t.split("\n")):
            old_h = [m.group(2).strip() for m in OLD_HEREDOC.finditer(t)]
            new_h = [b.strip() for b in mod.heredoc_code(t)]
        if old_i != new_i or old_h != new_h or old_drop_comments(mod, t) != mod.drop_comments(t):
            fails.append("a scan disagrees with its old form on %r: inline %r vs %r, heredoc %r vs %r"
                         % (t, old_i, new_i, old_h, new_h))
            break
    # Wall time through the hook, from a worktree, one command of the shape each scan was slow on.
    shapes = {
        "20000 lines, half of them comments, with quotes": "# c\necho 'x'\n" * 10000,
        "20000 interpreter heredoc openers": "python <<A\n" * 20000,
        "20000 interpreter words on one line": "python " * 20000,
        "a 60000-letter name before a call paren in inline code": "python3 -c '" + "a" * 60000 + " (\"/x\")'",
    }
    for name, cmd in shapes.items():
        for attempt in range(2):
            start = time.perf_counter()
            rc, err = run("Bash", {"command": cmd}, WT)
            took = time.perf_counter() - start
            if rc == 0 and took < 1.0:
                break
        else:
            fails.append("%s: rc=%s after %.2f s, wanted rc 0 under 1 s %s" % (name, rc, took, err.strip()[:100]))
    return fails


def main():
    try:
        build_fixture()
        if "--latency" in sys.argv:
            i = sys.argv.index("--latency")
            latency(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 200)
            return 0
        all_cases = cases()
        with ThreadPoolExecutor(max_workers=8) as pool:
            fails = [f for f in pool.map(check, all_cases) if f]
        fails += scaling_checks()
        n_block = sum(1 for c in all_cases if c[0] == "block")
        n_allow = sum(1 for c in all_cases if c[0] == "allow")
        n_mal = sum(1 for c in all_cases if c[0] == "malformed")
        n_main = sum(1 for c in all_cases if c[0] == "allow" and c[3] in (MAIN, NOREPO))
        print("worktree guard cases: %d block, %d allow (%d from the main checkout or no repo), %d malformed"
              % (n_block, n_allow, n_main, n_mal))
        if not n_block or not n_allow or not n_mal:
            print("zero cases processed")
            return 1
        if fails:
            print("\n%d FAILED:" % len(fails))
            for f in fails:
                print("  " + f)
            return 1
        print("all pass")
        return 0
    finally:
        shutil.rmtree(BASE, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
