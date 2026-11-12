#!/usr/bin/env python3
"""The measurement scripts (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py) give each `claude -p` session a login of its own:
the long-lived token of `claude setup-token`, stored under FORGE_MEASURE_OAUTH_TOKEN, passed as CLAUDE_CODE_OAUTH_TOKEN. They never
link or copy the machine's `.credentials.json` into the throwaway config dir: Claude Code rewrites that file by temp file plus rename,
which replaces a symlink with a regular file, so the rotated refresh token ended up only in the throwaway dir and the real login died
for every session on the machine (Linear DTC-43; docs in framework-discuss/research/login-compartido.md).

Everything runs offline against a stand-in `claude` (this test writes it; the PATH of every child holds only its own fake directory with
git and python3 linked in), a toy secret store with a FAKE value, and a toy HOME. No live session, no real store, no real credentials.

Cases (a) to (e) of the unit, each seen failing on the code before the change (master 3049392):
  (a) the child sees CLAUDE_CODE_OAUTH_TOKEN = the store's value, no ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN, the parent's own token is
      replaced, other variables are untouched, and its CLAUDE_CONFIG_DIR holds no `.credentials.json`.
      Red: "auto_mode: token in child: want 'tok-FAKE-...', got ''" and "auto_mode: credentials file in child's config dir: want False,
      got True" (same two lines for skill_bench).
  (b) a store without the key, with an empty one, or no store at all: exit != 0 before any child starts (the stand-in's log does not
      exist), one line naming FORGE_MEASURE_OAUTH_TOKEN and `claude setup-token`.
      Red: "... exit: want non-zero, got 0" and "... child started: want False, got True".
  (c) a `.credentials.json` symlink (and a regular file) left in the throwaway dir by an earlier run is gone before the child starts, and
      the file it pointed to keeps its inode, size and mtime. Red: "... leftover link seen by the child: want False, got True".
  (d) the fake token is in no file under the run's output directory, not in stdout or stderr, and not in the child's argv.
      Red: none on this code (it never carried the token) -- the control is `leaky` below: a stand-in that echoes its token makes
      this very check fail with "token found in ...", so the check is shown able to fail.
  (e) with HOME on a toy dir whose `.claude/.credentials.json` exists, nothing in the script's process opens, links, copies or lists
      anything under that `.claude` (a Python audit hook records it); the sandbox command of skill_bench never binds it.
      Red: "... touched the real home's .claude: want [], got [('os.symlink', ...)]".
Also: --bare is refused in front of a session; the helper's own cases (environment, empty token); the token reaches a bwrap-wrapped child
(NOT RUN, NOT ARMED when bubblewrap cannot start here)."""
import json
import os
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import sandbox  # noqa: E402

BENCH_DIR = os.path.join(sandbox.FORGE, "scripts", "bench")
AUTO = os.path.join(BENCH_DIR, "auto_mode.py")
SKILL = os.path.join(BENCH_DIR, "skill_bench.py")
sys.path.insert(0, BENCH_DIR)
KEY = "FORGE_MEASURE_OAUTH_TOKEN"
TOKEN = "tok-FAKE-0f3a9c51d7e24b68"
PARENT_TOKEN = "tok-PARENT-must-not-reach-the-child"
failures = []
not_run = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s: want %r, got %r" % (label, expected, got))


def put(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


# The stand-in records, outside the run's output dir, what a session would see; it prints a minimal stream. LEAK=1 makes it echo its
# token on stdout (the control of check (d)).
FAKE = r'''#!%(py)s
import json, os, sys
a = sys.argv[1:]
if a and a[0] == "--version":
    print("9.9.9 (Fake Claude)")
    sys.exit(0)
cfg = os.environ.get("CLAUDE_CONFIG_DIR", "")
cred = os.path.join(cfg, ".credentials.json")
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": a, "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "api_key": os.environ.get("ANTHROPIC_API_KEY"),
                         "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN"), "marker": os.environ.get("MEASURE_MARKER"),
                         "cfg": cfg, "cred_exists": os.path.lexists(cred), "cred_is_link": os.path.islink(cred)}) + "\n")
if os.environ.get("LEAK"):
    print("token is " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""))
print(json.dumps({"type": "result", "result": "ok", "is_error": False, "num_turns": 1, "total_cost_usd": 0.01,
                  "usage": {"input_tokens": 1, "output_tokens": 1}}))
'''

# Runs a script in-process under an audit hook: records every open, symlink, link, rename, copy or listing of a path under WATCH.
AUDIT = r'''
import os, runpy, sys
watch, log, script = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [script] + sys.argv[4:]
sys.path.insert(0, os.path.dirname(script))   # what running the script directly does; runpy.run_path does not
seen = []
def hook(ev, args):
    if ev in ("open", "os.symlink", "os.link", "os.rename", "os.listdir", "os.scandir", "shutil.copyfile", "shutil.copytree", "glob.glob"):
        for x in args:
            if isinstance(x, (str, bytes)) and str(x if isinstance(x, str) else x.decode()).startswith(watch):
                seen.append((ev, str(x)))
sys.addaudithook(hook)
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as e:
    code = e.code
else:
    code = 0
with open(log, "w") as fh:
    fh.write(repr(seen))
sys.exit(code if isinstance(code, int) else (1 if code else 0))
'''

ORACLE = "def check(repo, message):\n    return [{'id': 'x', 'passed': False, 'evidence': 'toy'}]\n"


def toy_bench(tmp):
    b = os.path.join(tmp, "bench")
    put(os.path.join(b, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    d = os.path.join(b, "tasks", "t0")
    put(os.path.join(d, "task.json"), json.dumps({"id": "t0", "field": "logic", "concept": "logic.arith", "difficulty": 1, "prompt": "Fix it.",
                                                   "source": {"kind": "authored"}, "message_required": False}))
    put(os.path.join(d, "repo", "calc.py"), "x = 1\n")
    put(os.path.join(d, "oracle.py"), ORACLE)
    return b


def tree_text(root, needle):
    """The files under root (links not followed) whose bytes hold `needle`."""
    hits = []
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            if os.path.islink(p):
                continue
            try:
                if needle.encode() in open(p, "rb").read():
                    hits.append(p)
            except OSError:
                pass
    return hits


def log_rows(log):
    return [json.loads(l) for l in open(log)] if os.path.exists(log) else []


def main():
    tmp = sandbox.mkdtemp("measure-login-")
    fakedir, home = os.path.join(tmp, "path"), os.path.join(tmp, "home")
    os.makedirs(fakedir)
    for prog in ("git", "python3"):
        real = subprocess.run(["sh", "-c", "command -v " + prog], capture_output=True, text=True).stdout.strip()
        os.symlink(real, os.path.join(fakedir, prog))
    fake = os.path.join(tmp, "claude")
    put(fake, FAKE % {"py": sys.executable}, 0o755)
    # the toy HOME holds a credentials file that nothing may touch
    real_cred = os.path.join(home, ".claude", ".credentials.json")
    put(real_cred, '{"toy": "real login"}', 0o600)
    store_ok = os.path.join(tmp, "store-ok.json")
    put(store_ok, json.dumps({"_comment": "toy", KEY: TOKEN}))
    store_nokey = os.path.join(tmp, "store-nokey.json")
    put(store_nokey, json.dumps({"OTHER": "x"}))
    store_empty = os.path.join(tmp, "store-empty.json")
    put(store_empty, json.dumps({KEY: "  "}))
    bench = toy_bench(tmp)
    counter = [0]

    def env_for(store, log, **extra):
        e = {"PATH": fakedir, "HOME": home, "TMPDIR": tmp, "FAKE_LOG": log, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
             "MEASURE_MARKER": "kept", "ANTHROPIC_API_KEY": "key-PARENT", "ANTHROPIC_AUTH_TOKEN": "auth-PARENT",
             "CLAUDE_CODE_OAUTH_TOKEN": PARENT_TOKEN}
        if store:
            e["FORGE_SECRETS_FILE"] = store
        e.update(extra)
        return e

    def run(script, which, store, extra_env=None, pre=None, wrapper=None):
        """Runs one session's worth of `which` (auto|skill) on the stand-in; returns (rc, text, log rows, out dir, audit seen)."""
        counter[0] += 1
        out = os.path.join(tmp, "out-%d" % counter[0])
        log = os.path.join(tmp, "fake-%d.log" % counter[0])
        os.makedirs(os.path.join(out, "agent-home"), exist_ok=True)
        if pre:
            pre(os.path.join(out, "agent-home"))
        if which == "auto":
            args = ["run", "--actions", "V1", "--contexts", "main-asked", "--claude-bin", fake, "--out", out, "--guard-cmd", "none", "--workers", "1"]
        else:
            args = ["run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out, "--k", "1", "--tasks", "t0", "--arm", "none"]
        env = env_for(store, log, **(extra_env or {}))
        audit_log = os.path.join(tmp, "audit-%d.txt" % counter[0])
        if wrapper:
            put(os.path.join(tmp, "audit.py"), AUDIT)
            cmd = [sys.executable, os.path.join(tmp, "audit.py"), os.path.join(home, ".claude"), audit_log, script] + args
        else:
            cmd = [sys.executable, script] + args
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300, stdin=subprocess.DEVNULL)
        seen = eval(open(audit_log).read()) if os.path.exists(audit_log) else None
        return r.returncode, r.stdout + r.stderr, log_rows(log), out, seen

    scripts = (("auto_mode", AUTO, "auto"), ("skill_bench", SKILL, "skill"))

    # (a) the child's environment and config dir
    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok)
        want("%s: a session ran" % name, len(rows) >= 1, True)
        for row in rows[:1]:
            want("%s: token in child" % name, row["token"], TOKEN)
            want("%s: ANTHROPIC_API_KEY in child" % name, row["api_key"], None)
            want("%s: ANTHROPIC_AUTH_TOKEN in child" % name, row["auth_token"], None)
            want("%s: another variable of the parent is untouched" % name, row["marker"], "kept")
            want("%s: credentials file in child's config dir" % name, row["cred_exists"], False)
            want("%s: child's config dir is the throwaway agent-home" % name, row["cfg"], os.path.join(out, "agent-home"))
        # (d) the value is nowhere it should not be
        want("%s: files under the output dir holding the token" % name, tree_text(out, TOKEN), [])
        want("%s: token on stdout or stderr" % name, TOKEN in text, False)
        want("%s: token on the child's command line" % name, [r for r in rows if any(TOKEN in x for x in r["argv"])], [])
        want("%s: parent's own token on stdout, stderr or in files" % name, (PARENT_TOKEN in text, tree_text(out, PARENT_TOKEN)), (False, []))

    # (d) control: a stand-in that prints its token makes the same check fail, so the check can fail
    code, text, rows, out, _ = run(AUTO, "auto", store_ok, extra_env={"LEAK": "1"})
    leaked = tree_text(out, TOKEN)
    want("control (d): a child that prints its token is seen in the output dir (this check can fail)", bool(leaked), True)

    # (b) the key missing: no session starts, one line names the key and the fix
    for label, store in (("key absent", store_nokey), ("key empty", store_empty), ("no store", os.path.join(tmp, "missing.json"))):
        for name, script, which in scripts:
            code, text, rows, out, _ = run(script, which, store)
            want("%s, %s: exit" % (name, label), code != 0, True)
            want("%s, %s: child started" % (name, label), len(rows) > 0, False)
            want("%s, %s: names the key and the fix" % (name, label), (KEY in text, "claude setup-token" in text, "Traceback" in text), (True, True, False))
            want("%s, %s: the parent's token is not printed" % (name, label), PARENT_TOKEN in text, False)

    # (c) a leftover credentials link and file in the throwaway dir
    target = os.path.join(tmp, "target-creds.json")
    put(target, '{"toy": "target"}', 0o600)
    os.utime(target, (1_000_000_000, 1_000_000_000))
    st0 = os.stat(target)
    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok, pre=lambda d: os.symlink(target, os.path.join(d, ".credentials.json")))
        want("%s: leftover link seen by the child" % name, [r["cred_exists"] for r in rows[:1]], [False])
        st1 = os.stat(target)
        want("%s: target of the leftover link unchanged (inode, size, mtime)" % name,
             (st1.st_ino, st1.st_size, st1.st_mtime), (st0.st_ino, st0.st_size, st0.st_mtime))
        want("%s: target content unchanged" % name, open(target).read(), '{"toy": "target"}')
        code, text, rows, out, _ = run(script, which, store_ok, pre=lambda d: put(os.path.join(d, ".credentials.json"), "{}"))
        want("%s: leftover regular file seen by the child" % name, [r["cred_exists"] for r in rows[:1]], [False])

    # (e) the real home's .claude is never touched
    st_real = os.stat(real_cred)
    for name, script, which in scripts:
        code, text, rows, out, seen = run(script, which, store_ok, wrapper=True)
        want("%s (audited): a session ran (output: %s)" % (name, text[-300:] if not rows else ""), len(rows) >= 1, True)
        want("%s: touched the real home's .claude" % name, seen, [])
    want("real home's credentials file unchanged", (os.stat(real_cred).st_ino, os.stat(real_cred).st_mtime, stat.S_ISREG(os.stat(real_cred).st_mode)),
         (st_real.st_ino, st_real.st_mtime, True))
    # control of (e): the audit wrapper does see a touch (a script that links the toy credentials file)
    probe = os.path.join(tmp, "probe.py")
    put(probe, "import os, sys\nos.symlink(os.path.join(os.path.expanduser('~'), '.claude', '.credentials.json'), sys.argv[1])\n")
    put(os.path.join(tmp, "audit.py"), AUDIT)
    alog = os.path.join(tmp, "audit-control.txt")
    subprocess.run([sys.executable, os.path.join(tmp, "audit.py"), os.path.join(home, ".claude"), alog, probe, os.path.join(tmp, "probe-link")],
                   env=dict(os.environ, HOME=home), capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    want("control (e): the audit wrapper records a symlink of the real credentials file", "os.symlink" in (open(alog).read() if os.path.exists(alog) else ""), True)

    # the helper and the sandbox command, in-process
    try:
        import measure_login as ml  # noqa: E402
    except ImportError as e:
        failures.append("measure_login helper: %s" % e)
        ml = None
    if ml:
        sec = os.path.join(tmp, "sec-unit.json")
        put(sec, json.dumps({KEY: " " + TOKEN + "\n"}))
        parent = {"A": "1", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": "p"}
        env = ml.child_env(parent, secrets_file=sec)
        want("helper: environment", env, {"A": "1", "CLAUDE_CODE_OAUTH_TOKEN": TOKEN})
        want("helper: the parent's dict is not changed", parent["ANTHROPIC_API_KEY"], "k")
        for bad in (store_nokey, store_empty, os.path.join(tmp, "missing.json")):
            try:
                ml.child_env({}, secrets_file=bad)
                failures.append("helper: no refusal for %s" % os.path.basename(bad))
            except ml.LoginError as e:
                want("helper: the refusal names key and fix (%s)" % os.path.basename(bad), (KEY in str(e), "claude setup-token" in str(e), "\n" in str(e)), (True, True, False))
        try:
            ml.refuse_bare(["claude", "-p", "x", "--bare"])
            failures.append("helper: --bare accepted")
        except ml.LoginError as e:
            want("helper: --bare refusal names the reason", "--bare" in str(e) and "OAUTH" in str(e), True)
        want("helper: a command without --bare passes", ml.refuse_bare(["claude", "-p", "x"]), None)
        d = os.path.join(tmp, "cfgdir")
        os.makedirs(d)
        os.symlink(target, os.path.join(d, ".credentials.json"))
        ml.clean_config_dir(d)
        want("helper: clean_config_dir removes a link and keeps its target", (os.path.lexists(os.path.join(d, ".credentials.json")), os.path.exists(target)), (False, True))

    import skill_bench as sb  # noqa: E402
    work, ahome = os.path.join(tmp, "w"), os.path.join(tmp, "ah")
    os.makedirs(work)
    os.makedirs(ahome)
    saved = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        cmd = sb.wrap(["claude", "-p", "x"], "bwrap", work, ahome, fake) if shutil.which("bwrap") else None
    finally:
        os.environ["HOME"] = saved
    if cmd:
        want("wrap(): no bind mentions a credentials file", [c for c in cmd if ".credentials.json" in c], [])
        # the token reaches a bwrap child: the environment is passed on unless bwrap is told otherwise
        probe_cmd = [c for c in cmd[:cmd.index("--")]] + ["--", "sh", "-c", 'printf %s "$CLAUDE_CODE_OAUTH_TOKEN"']
        r = subprocess.run(probe_cmd, capture_output=True, text=True, env=dict(os.environ, HOME=home, CLAUDE_CODE_OAUTH_TOKEN=TOKEN),
                           timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            not_run.append("token reaches a bwrap child -> NOT RUN, NOT ARMED: bwrap cannot start here (rc %s)" % r.returncode)
        else:
            want("a bwrap-wrapped child sees the token", r.stdout, TOKEN)
    else:
        not_run.append("wrap() and bwrap child -> NOT RUN, NOT ARMED: no bwrap on PATH")

    for msg in failures:
        print("FAIL", msg)
    for msg in not_run:
        print(msg)
    print("%d failure(s)" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
