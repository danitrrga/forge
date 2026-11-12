#!/usr/bin/env python3
"""The measurement scripts (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py) give each `claude -p` session a login of its own:
the long-lived token of `claude setup-token`, stored under FORGE_MEASURE_OAUTH_TOKEN, passed as CLAUDE_CODE_OAUTH_TOKEN. They never
link or copy the machine's `.credentials.json` into the throwaway config dir: Claude Code rewrites that file by temp file plus rename,
which replaces a symlink with a regular file, so the rotated refresh token ended up only in the throwaway dir and the real login died
for every session on the machine (a refresh in the throwaway dir logged the machine's real login out).

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
  (d) the fake token is in no file the run keeps (output directory, kept working copy or world, `.gz` read decompressed), not in stdout
      or stderr, not in the child's argv, also when the agent prints its environment (stream, a work file, a transcript) and also on
      the timeout path: the harness replaces it by a placeholder. Control: the same runs with the redaction switched off find it in both
      scripts. Red on 39df9d2: "files holding the token: want [], got ['.../transcripts/....jsonl', '.../agent.jsonl', '.../work/leak.txt']".
  Review of the first version added: the variables that change credential or endpoint are dropped, the store error says what failed and
  where the store is, a redirected store is said on stderr, a login file that cannot be removed and a malformed token value end the run
  with one line, no private path or ticket id in engine files.
  (e) with HOME on a toy dir whose `.claude/.credentials.json` exists, nothing in the script's process opens, links, copies or lists
      anything under that `.claude` (a Python audit hook records it); the sandbox command of skill_bench never binds it.
      Red: "... touched the real home's .claude: want [], got [('os.symlink', ...)]".
Also: --bare is refused in front of a session; the helper's own cases (environment, empty token); the token reaches a bwrap-wrapped child
(NOT RUN, NOT ARMED when bubblewrap cannot start here)."""
import gzip
import json
import os
import shutil
import stat
import subprocess
import sys
import zlib

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
PLACEHOLDER = "[REDACTED: measurement token]"
# what the child must not inherit (one statement here, independent of the helper's own list)
DROPPED = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
           "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES"]
failures = []
not_run = []


def want(label, got, expected):
    if got != expected:
        failures.append("%s: want %r, got %r" % (label, expected, got))


def put(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:   # 0o000 is a mode too
        os.chmod(path, mode)


# The stand-in records, outside the run's output dir, what a session would see; it prints a minimal stream. LEAK=1 makes it echo its
# token on stdout (the control of check (d)).
FAKE = r'''#!%(py)s
import json, os, re, sys, time
a = sys.argv[1:]
if a and a[0] == "--version":
    print("9.9.9 (Fake Claude)")
    sys.exit(0)
cfg = os.environ.get("CLAUDE_CONFIG_DIR", "")
cred = os.path.join(cfg, ".credentials.json")
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": a, "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "api_key": os.environ.get("ANTHROPIC_API_KEY"),
                         "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN"), "marker": os.environ.get("MEASURE_MARKER"),
                         "dropped": {k: os.environ.get(k) for k in %(dropped)r}, "cfg": cfg, "cred_exists": os.path.lexists(cred), "cred_is_link": os.path.islink(cred)}) + "\n")
if os.environ.get("LEAK"):   # an agent that runs `env`: the token on stdout, in a file of the work dir and in its session transcript
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    print(json.dumps({"type": "user", "message": "env says CLAUDE_CODE_OAUTH_TOKEN=" + tok}))
    open("leak.txt", "w").write("CLAUDE_CODE_OAUTH_TOKEN=" + tok + "\n")
    if "--session-id" in a:
        d = os.path.join(cfg, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd())))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, a[a.index("--session-id") + 1] + ".jsonl"), "w").write(json.dumps({"type": "user", "text": "env: " + tok}) + "\n")
sys.stdout.flush()
if os.environ.get("SLEEP"):   # a session that outlives --timeout, killed after it leaked
    time.sleep(float(os.environ["SLEEP"]))
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

# Runs a script with the redaction switched off, so the leak checks can be seen failing (their negative control).
NOREDACT = r'''
import os, runpy, sys
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(script))
import measure_login
measure_login.redact_tree = lambda *a, **k: 0
measure_login.redact_text = lambda text, tok: text or ""
runpy.run_path(script, run_name="__main__")
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
    """The files under root (links not followed) whose bytes hold `needle`, a `.gz` file also through its decompressed bytes."""
    hits = []
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            if os.path.islink(p):
                continue
            try:
                data = open(p, "rb").read()
                if f.endswith(".gz"):
                    try:
                        data += b"\n" + gzip.decompress(data)
                    except (OSError, EOFError, zlib.error):
                        pass
                if needle.encode() in data:
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
    put(fake, FAKE % {"py": sys.executable, "dropped": DROPPED}, 0o755)
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
             "CLAUDE_CODE_OAUTH_TOKEN": PARENT_TOKEN, "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_USE_FOUNDRY": "1",
             "ANTHROPIC_BASE_URL": "https://example.test", "CLAUDE_CODE_SIMPLE": "1", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "REFRESH-PARENT",
             "CLAUDE_CODE_OAUTH_SCOPES": "user:inference"}
        if store:
            e["FORGE_SECRETS_FILE"] = store
        e.update(extra)
        return e

    def run(script, which, store, extra_env=None, pre=None, wrapper=None, keep=False, noredact=False, more=()):
        """Runs one session's worth of `which` (auto|skill) on the stand-in; returns (rc, text, log rows, out dir, audit seen)."""
        counter[0] += 1
        out = os.path.join(tmp, "out-%d" % counter[0])
        log = os.path.join(tmp, "fake-%d.log" % counter[0])
        os.makedirs(os.path.join(out, "agent-home"), exist_ok=True)
        if pre:
            pre(os.path.join(out, "agent-home"))
        if which == "auto":
            args = ["run", "--actions", "V1", "--contexts", "main-asked", "--claude-bin", fake, "--out", out, "--guard-cmd", "none", "--workers", "1"]
            args += ["--keep-world"] if keep else []
        else:
            args = ["run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none", "--out", out, "--k", "1", "--tasks", "t0", "--arm", "none"]
            args += ["--keep-work"] if keep else []
        args += list(more)
        env = env_for(store, log, **(extra_env or {}))
        audit_log = os.path.join(tmp, "audit-%d.txt" % counter[0])
        if wrapper:
            put(os.path.join(tmp, "audit.py"), AUDIT)
            cmd = [sys.executable, os.path.join(tmp, "audit.py"), os.path.join(home, ".claude"), audit_log, script] + args
        elif noredact:
            put(os.path.join(tmp, "noredact.py"), NOREDACT)
            cmd = [sys.executable, os.path.join(tmp, "noredact.py"), script] + args
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
            want("%s: the variables that change credential or endpoint are dropped" % name,
                 {k: v for k, v in row["dropped"].items() if v is not None}, {})
            want("%s: another variable of the parent is untouched" % name, row["marker"], "kept")
            want("%s: credentials file in child's config dir" % name, row["cred_exists"], False)
            want("%s: child's config dir is the throwaway agent-home" % name, row["cfg"], os.path.join(out, "agent-home"))
        # (d) the value is nowhere it should not be
        want("%s: files under the output dir holding the token" % name, tree_text(out, TOKEN), [])
        want("%s: token on stdout or stderr" % name, TOKEN in text, False)
        want("%s: token on the child's command line" % name, [r for r in rows if any(TOKEN in x for x in r["argv"])], [])
        want("%s: parent's own token on stdout, stderr or in files" % name, (PARENT_TOKEN in text, tree_text(out, PARENT_TOKEN)), (False, []))

    # (d) an agent that runs `env`: stdout, a work-dir file and a session transcript all hold the token. Everything the run keeps is
    # scanned (gzip decompressed). With the redaction on, none holds it and the placeholder is there; with it off (control), the same scan
    # finds it, in the gzipped transcript of skill_bench too.
    def kept_dirs(out):
        return [out] + [os.path.join(tmp, d) for d in os.listdir(tmp) if d.startswith("auto-mode-2")]

    def drop_worlds():
        for d in [d for d in os.listdir(tmp) if d.startswith("auto-mode-2")]:
            shutil.rmtree(os.path.join(tmp, d), ignore_errors=True)

    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok, extra_env={"LEAK": "1"}, keep=True)
        want("%s, agent printed its env: a session ran" % name, len(rows) >= 1, True)
        want("%s, agent printed its env: files holding the token" % name, [h for k in kept_dirs(out) for h in tree_text(k, TOKEN)], [])
        want("%s, agent printed its env: token on stdout or stderr" % name, TOKEN in text, False)
        marked = sorted({os.path.basename(h) for k in kept_dirs(out) for h in tree_text(k, PLACEHOLDER)})
        want("%s, agent printed its env: the placeholder is in the work file" % name, "leak.txt" in marked, True)
        want("%s, agent printed its env: the placeholder is in the stream or transcript" % name,
             any(m.endswith(".gz") or m.endswith(".jsonl") for m in marked), True)
        drop_worlds()
        code, text, rows, out, _ = run(script, which, store_ok, extra_env={"LEAK": "1"}, keep=True, noredact=True)
        hits = sorted(os.path.basename(h) for k in kept_dirs(out) for h in tree_text(k, TOKEN))
        want("control (d) %s: with the redaction off the scan finds the token in the work file" % name, "leak.txt" in hits, True)
        want("control (d) %s: ... and in the stream or transcript (gzip included)" % name,
             any(h.endswith(".gz") or h.endswith(".jsonl") for h in hits), True)
        drop_worlds()

    # (b) the key missing: no session starts, one line names the key and the fix
    for label, store in (("key absent", store_nokey), ("key empty", store_empty), ("no store", os.path.join(tmp, "missing.json"))):
        for name, script, which in scripts:
            code, text, rows, out, _ = run(script, which, store)
            want("%s, %s: exit" % (name, label), code != 0, True)
            want("%s, %s: child started" % (name, label), len(rows) > 0, False)
            want("%s, %s: names the key and the fix" % (name, label), (KEY in text, "claude setup-token" in text, "Traceback" in text), (True, True, False))
            want("%s, %s: the parent's token is not printed" % (name, label), PARENT_TOKEN in text, False)

    # the same on the timeout path: the session leaked, then outlived --timeout and was killed
    for name, script, which in scripts:
        for noredact in (False, True):
            code, text, rows, out, _ = run(script, which, store_ok, extra_env={"LEAK": "1", "SLEEP": "30"}, keep=True, noredact=noredact,
                                           more=["--timeout", "3"])
            hits = [h for k in kept_dirs(out) for h in tree_text(k, TOKEN)]
            want("%s, timed-out session that leaked, redaction %s: files holding the token" % (name, "off (control)" if noredact else "on"),
                 bool(hits), noredact)
            drop_worlds()

    # the error says what failed and where the store is; a store that is no good in any way starts nothing and ends the whole run
    store_dir = os.path.join(tmp, "store-dir")
    os.makedirs(store_dir)
    store_bin = os.path.join(tmp, "store-binary.json")
    put(store_bin, "{not json")
    store_arr = os.path.join(tmp, "store-array.json")
    put(store_arr, "[1, 2]")
    store_int = os.path.join(tmp, "store-int.json")
    put(store_int, json.dumps({KEY: 5}))
    store_nul = os.path.join(tmp, "store-nul.json")
    put(store_nul, json.dumps({KEY: "tok-BADVALUE\x00x"}))
    store_sur = os.path.join(tmp, "store-surrogate.json")
    put(store_sur, json.dumps({KEY: "tok-BADVALUE\ud800x"}))
    store_sp = os.path.join(tmp, "store-space.json")
    put(store_sp, json.dumps({KEY: "tok-BADVALUE x"}))
    store_deep = os.path.join(tmp, "store-deep.json")
    put(store_deep, "[" * 200000)
    store_000 = os.path.join(tmp, "store-000.json")
    put(store_000, json.dumps({KEY: TOKEN}), 0o000)
    variants = [("missing file", os.path.join(tmp, "missing.json"), "does not exist"), ("a directory", store_dir, "is a directory"),
                ("not JSON", store_bin, "not valid JSON"), ("nested too deep for the parser", store_deep, "not valid JSON"), ("a JSON array", store_arr, "not an object"), ("key absent", store_nokey, "is not in the store"),
                ("key empty", store_empty, "is empty"), ("key not a string", store_int, "not a string"),
                ("NUL in the value", store_nul, "cannot be in a token"), ("lone surrogate in the value", store_sur, "cannot be in a token"),
                ("space inside the value", store_sp, "cannot be in a token")]
    if os.geteuid() != 0:
        variants.append(("unreadable file", store_000, "cannot be read"))
    else:
        not_run.append("unreadable store case -> NOT RUN, NOT ARMED: running as root, mode 000 is readable")
    for label, store, cause in variants:
        for name, script, which in scripts:
            code, text, rows, out, _ = run(script, which, store)
            want("%s, store %s: exit (the whole run, not 0 with invalid jobs)" % (name, label), code != 0, True)
            want("%s, store %s: child started" % (name, label), len(rows), 0)
            want("%s, store %s: says what failed, names the store, the key and the fix" % (name, label),
                 (cause in text, store in text, KEY in text, "claude setup-token" in text, "Traceback" in text), (True, True, True, True, False))
            want("%s, store %s: no part of the bad value is echoed" % (name, label), "BADVALUE" in text or TOKEN in text, False)
            want("%s, store %s: one error line" % (name, label), len([l for l in text.splitlines() if "no measurement login" in l]), 1)
    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok)
        want("%s: a redirected store is said on stderr, with its path, never the value" % name,
             (("redirected by FORGE_SECRETS_FILE to %s" % store_ok) in text, TOKEN in text), (True, False))
    # a throwaway dir whose `.credentials.json` cannot be removed (a directory): one line, no traceback, no session, exit non-zero
    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok, pre=lambda d: os.makedirs(os.path.join(d, ".credentials.json", "sub")))
        want("%s, a directory named .credentials.json: refused with one line" % name,
             (code != 0, len(rows), "Traceback" in text, ".credentials.json" in text), (True, 0, False, True))

    # no private reference in an engine file; the root README says the key is needed
    for rel in ("scripts/bench/measure_login.py", "scripts/bench/auto_mode.py", "scripts/bench/skill_bench.py", "tests/test_measure_login.py",
                "tests/sandbox.py", "benchmarks/skill-bench/README.md"):
        body = open(os.path.join(sandbox.FORGE, rel)).read()
        private = ("framework" + "-discuss", "DTC" + "-", "login-" + "compartido")   # joined here so this file does not hold them itself
        want("%s: no private path or ticket id" % rel, [w for w in private if w in body], [])
    want("README.md quick-start names the key", KEY in open(os.path.join(sandbox.FORGE, "README.md")).read(), True)

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
        # a corrupt .gz (valid header, damaged stream: zlib.error, which is not an OSError) must not stop the scan of the files after it
        rdir = os.path.join(tmp, "redact-unit")
        os.makedirs(rdir)
        bad = bytearray(gzip.compress(b"x" * 1000 + b"hello world" * 50))
        bad[10] ^= 0xFF
        with open(os.path.join(rdir, "a-corrupt.gz"), "wb") as fh:
            fh.write(bytes(bad))
        put(os.path.join(rdir, "b-plain.txt"), "TOKEN=" + TOKEN + " and json " + json.dumps({"t": TOKEN}) + "\n")
        with open(os.path.join(rdir, "c-good.gz"), "wb") as fh:
            fh.write(gzip.compress(("x " + TOKEN).encode()))
        try:
            n = ml.redact_tree(rdir, TOKEN)
        except Exception as e:   # noqa: BLE001
            n = "raised %s: %s" % (type(e).__name__, e)
        want("helper: redact_tree survives a corrupt .gz and redacts the rest (files changed)", n, 2)
        want("helper: redact_tree leaves no token in the plain or the gzipped file",
             tree_text(rdir, TOKEN), [])
        want("helper: redact_text", (ml.redact_text("a " + TOKEN + " b", TOKEN), ml.redact_text(None, TOKEN)), ("a " + PLACEHOLDER + " b", ""))
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
