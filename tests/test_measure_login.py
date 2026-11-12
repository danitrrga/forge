#!/usr/bin/env python3
"""The measurement scripts (scripts/bench/auto_mode.py, scripts/bench/skill_bench.py) give each `claude -p` session a login of its own:
the long-lived token of `claude setup-token`, stored under FORGE_MEASURE_OAUTH_TOKEN, passed as CLAUDE_CODE_OAUTH_TOKEN. They never
link or copy the machine's `.credentials.json` into the throwaway config dir: Claude Code rewrites that file by temp file plus rename,
which replaces a symlink with a regular file, so the rotated refresh token ended up only in the throwaway dir and the real login died
for every session on the machine (a refresh in the throwaway dir logged the machine's real login out).

Everything runs offline against a stand-in `claude` (this test writes it; the PATH of every child holds only its own fake directory with
git and python3 linked in), a toy secret store with a FAKE value, and a toy HOME. No live session, no real store, no real credentials.

What the run stores. The harness writes text a session produced (stream, stderr, hook log, transcripts) as a NEW file with the token
replaced by a placeholder; it never opens, rewrites or decompresses a file the agent produced (its work files, archives, links, special
files are kept as they are). Cases, each seen failing on the code before it:
  (a) the child sees CLAUDE_CODE_OAUTH_TOKEN = the store's value, none of the variables that change credential or endpoint, the other
      variables of the parent unchanged, and a config dir without `.credentials.json`.
  (b) a store that is no good (missing, a directory, unreadable, not JSON, not an object, key absent or empty, not a plausible token:
      too short, too long, non-ASCII, a space or control character): one line naming the cause, the store and the fix, a non-zero exit,
      no child started, no value echoed.
  (c) a `.credentials.json` link or file left in auto_mode's config dir is gone before the child starts, its target untouched; one that
      cannot be removed ends the run with one line.
  (d) a session that prints its environment: the stream, stderr, hook log and transcript the run stores hold the placeholder and not the
      token (skill_bench's `.gz` too, with and without --keep-work, on the timeout path too); the file the agent wrote itself is untouched
      (a hard link outside the run too), a FIFO in the work dir hangs nothing, a FIFO or link among the transcripts is never opened. A
      transcript that cannot be stored leaves nothing under its name. Control: with the redaction switched off the same runs hold the token.
  (d2) text from outside the harness that reaches what it stores or prints: a check that prints a work file holding the token, an oracle
      error with it, `claude --version`, an error naming a file: result.json, run.json, cells.tsv and the printed lines hold the
      placeholder; the same runs with the redaction switched off hold the token.
  (e) with HOME on a toy dir whose `.claude/.credentials.json` exists, nothing in the script's process opens, links, copies or lists
      anything under that `.claude`; the sandbox command of skill_bench never binds it.
  (f) skill_bench jobs have a config dir of their own: what the first job writes there (settings, a marker) is not seen by the second.
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
TOKEN = "tok-FAKE-0f3a9c51d7e24b68"   # 25 characters: a plausible shape
PARENT_TOKEN = "tok-PARENT-must-not-reach-the-child"
PLACEHOLDER = "[REDACTED: measurement token]"
# what the child must not inherit (one statement here, independent of the helper's own list)
DROPPED = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
           "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SIMPLE",
           "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES"]
# what must reach the child as the parent had it: only the drop list and the token change
PASSED = {"HTTPS_PROXY": "http://proxy.example.test:3128", "NO_PROXY": "localhost", "ANTHROPIC_MODEL": "toy-model",
          "ANTHROPIC_DEFAULT_SONNET_MODEL": "toy-sonnet", "CLAUDE_CODE_SUBAGENT_MODEL": "toy-sub", "NODE_EXTRA_CA_CERTS": "/srv/ca.pem",
          "AWS_PROFILE": "toy-aws"}
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
    print("9.9.9 (Fake Claude)" + (" " + json.load(open(os.environ["FORGE_SECRETS_FILE"]))["FORGE_MEASURE_OAUTH_TOKEN"] if os.environ.get("VERSION_LEAK") else ""))
    sys.exit(0)
cfg = os.environ.get("CLAUDE_CONFIG_DIR", "")
cred = os.path.join(cfg, ".credentials.json")
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(json.dumps({"argv": a, "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "api_key": os.environ.get("ANTHROPIC_API_KEY"),
                         "auth_token": os.environ.get("ANTHROPIC_AUTH_TOKEN"), "marker": os.environ.get("MEASURE_MARKER"),
                         "dropped": {k: os.environ.get(k) for k in %(dropped)r}, "pass": {k: os.environ.get(k) for k in %(passed)r},
                         "seen_settings": open(os.path.join(cfg, "settings.json")).read() if os.path.exists(os.path.join(cfg, "settings.json")) else None,
                         "seen_marker": os.path.exists(os.path.join(cfg, "marker")), "cwd": os.getcwd(),
                         "cfg": cfg, "cred_exists": os.path.lexists(cred), "cred_is_link": os.path.islink(cred)}) + "\n")
if os.environ.get("WRITE_SETTINGS"):   # session-written state: a settings file and a marker in the config dir
    open(os.path.join(cfg, "settings.json"), "w").write('{"model": "evil"}')
    open(os.path.join(cfg, "marker"), "w").write("x")
if os.environ.get("LEAK"):   # an agent that runs `env`: the token on stdout and stderr, in a file of the work dir, in the hook log and the transcript
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    print(json.dumps({"type": "user", "message": "env says CLAUDE_CODE_OAUTH_TOKEN=" + tok}))
    print("stderr says " + tok, file=sys.stderr)
    open("leak.txt", "w").write("CLAUDE_CODE_OAUTH_TOKEN=" + tok + "\n")
    os.mkfifo("pipe")   # a FIFO in the work dir: nothing of the harness may open it
    if os.environ.get("HARDLINK_TARGET"):
        os.link(os.environ["HARDLINK_TARGET"], "hl.txt")
    if "--settings" in a:   # the hook the toy settings file installs logs the tool output, which here holds the token
        import subprocess
        hook = json.load(open(a[a.index("--settings") + 1]))["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        subprocess.run(hook, shell=True, input=json.dumps({"tool_response": "env: " + tok}), text=True)
    if "--session-id" in a:
        d = os.path.join(cfg, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd())))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, a[a.index("--session-id") + 1] + ".jsonl"), "w").write(json.dumps({"type": "user", "text": "env: " + tok}) + "\n")
        if os.environ.get("TRANSCRIPT_FIFO"):
            os.mkfifo(os.path.join(d, "x-" + tok + ".fifo"))
        if os.environ.get("TRANSCRIPT_LINK"):
            os.symlink(os.environ["TRANSCRIPT_LINK"], os.path.join(d, "x.link"))
if os.environ.get("DENY_REASON"):   # a classifier denial whose reason text holds the token: the hook log and the transcript carry it, and so would the evidence
    import subprocess, uuid
    cmd = re.search(r"`([^`]+)`", a[a.index("-p") + 1]).group(1)
    tid = "toolu_" + uuid.uuid4().hex[:8]
    sid = a[a.index("--session-id") + 1]
    reason = ("Permission for this action was denied by the Claude Code auto mode classifier. Reason: [External System Writes] "
              + os.environ["CLAUDE_CODE_OAUTH_TOKEN"])
    payload = {"session_id": sid, "cwd": os.getcwd(), "tool_name": "Bash", "tool_input": {"command": cmd}, "tool_use_id": tid,
               "hook_event_name": "PermissionDenied", "reason": reason}
    for g in json.load(open(a[a.index("--settings") + 1]))["hooks"]["PermissionDenied"]:
        for h in g["hooks"]:
            subprocess.run(h["command"], shell=True, input=json.dumps(payload), text=True)
    lines = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}},
             {"type": "user", "toolDenialKind": "automode-blocked", "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": tid, "content": reason, "is_error": True}]}}]
    d = os.path.join(cfg, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd())))
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, sid + ".jsonl"), "w").write("".join(json.dumps(l) + "\n" for l in lines))
    for l in lines:
        print(json.dumps(l))
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
measure_login.redact_bytes = lambda data, tok: data
measure_login.redact_text = lambda text, tok: text or ""
runpy.run_path(script, run_name="__main__")
'''

ORACLE = "def check(repo, message):\n    return [{'id': 'x', 'passed': False, 'evidence': 'toy'}]\n"


LEAKY = {"evidence": "def check(repo, message):\n    return [{'id': 'x', 'passed': False, 'evidence': open(repo + '/leak.txt').read()}]\n",
         "crash": "def check(repo, message):\n    raise RuntimeError(open(repo + '/leak.txt').read().strip())\n"}


def toy_bench(tmp, n=2, name="bench", oracles=None):
    b = os.path.join(tmp, name)
    put(os.path.join(b, "concepts.json"), json.dumps({"logic.arith": {"field": "logic", "title": "arithmetic"}}))
    for i in range(n):
        d = os.path.join(b, "tasks", "t%d" % i)
        put(os.path.join(d, "task.json"), json.dumps({"id": "t%d" % i, "field": "logic", "concept": "logic.arith", "difficulty": 1, "prompt": "Fix it %d." % i,
                                                       "source": {"kind": "authored"}, "message_required": False}))
        put(os.path.join(d, "repo", "calc.py"), "x = 1\n")
        put(os.path.join(d, "oracle.py"), LEAKY[oracles[i]] if oracles else ORACLE)
    return b


def tree_text(root, needle):
    """The files under root (links not followed) whose bytes hold `needle`, a `.gz` file also through its decompressed bytes."""
    hits = []
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            if not stat.S_ISREG(os.lstat(p).st_mode):   # a link, a FIFO (opening it would block): not read
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


def stored_text(out):
    """The files of a run directory the harness wrote from session text: everything except the agent's work dir and the config dirs."""
    found = []
    for r, dirs, fs in os.walk(out):
        dirs[:] = [d for d in dirs if d not in ("work", "agent-home")]
        found += [os.path.join(r, f) for f in fs]
    return sorted(found)


def holding(files, needle):
    """The files among `files` whose bytes, or whose gunzipped bytes, hold `needle`."""
    hits = []
    for p in files:
        try:
            if not stat.S_ISREG(os.lstat(p).st_mode):
                continue
            data = open(p, "rb").read()
            if p.endswith(".gz"):
                data += b"\n" + gzip.decompress(data)
            if needle.encode() in data:
                hits.append(p)
        except (OSError, EOFError, zlib.error):
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
    put(fake, FAKE % {"py": sys.executable, "dropped": DROPPED, "passed": sorted(PASSED)}, 0o755)
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
    leaky_bench = toy_bench(tmp, name="bench-leaky", oracles=["evidence", "crash"])   # a check that prints a work file; an oracle that errors with its text
    counter = [0]

    def env_for(store, log, **extra):
        e = {"PATH": fakedir, "HOME": home, "TMPDIR": tmp, "FAKE_LOG": log, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
             "MEASURE_MARKER": "kept", "ANTHROPIC_API_KEY": "key-PARENT", "ANTHROPIC_AUTH_TOKEN": "auth-PARENT",
             "CLAUDE_CODE_OAUTH_TOKEN": PARENT_TOKEN, "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_USE_FOUNDRY": "1",
             "ANTHROPIC_BASE_URL": "https://example.test", "CLAUDE_CODE_SIMPLE": "1", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "REFRESH-PARENT",
             "CLAUDE_CODE_OAUTH_SCOPES": "user:inference", "CLAUDE_CODE_USE_MANTLE": "1", "CLAUDE_CODE_USE_ANTHROPIC_AWS": "1"}
        e.update(PASSED)
        if store:
            e["FORGE_SECRETS_FILE"] = store
        e.update(extra)
        return e

    def run(script, which, store, extra_env=None, pre=None, wrapper=None, keep=False, noredact=False, more=(), tasks="t0", workers="1", actions="V1", bench_dir=None):
        """Runs one session's worth of `which` (auto|skill) on the stand-in; returns (rc, text, log rows, out dir, audit seen)."""
        counter[0] += 1
        out = os.path.join(tmp, "out-%d" % counter[0])
        log = os.path.join(tmp, "fake-%d.log" % counter[0])
        os.makedirs(os.path.join(out, "agent-home"), exist_ok=True)
        if pre:
            pre(os.path.join(out, "agent-home"))
        if which == "auto":
            args = ["run", "--actions", actions, "--contexts", "main-asked", "--claude-bin", fake, "--out", out, "--guard-cmd", "none", "--workers", "1"]
            args += ["--keep-world"] if keep else []
        else:
            args = ["run", "--bench", bench_dir or bench, "--claude-bin", fake, "--sandbox", "none", "--out", out, "--k", "1", "--tasks", tasks, "--arm", "none",
                    "--workers", workers]
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
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=40, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:   # a run that does not end is a failure of its own, not a crash of this test
            failures.append("%s run hung (killed after 40 s): LEAK=%s, extra env %s" % (os.path.basename(script), bool((extra_env or {}).get("LEAK")), sorted(extra_env or {})))
            return 124, "hung", log_rows(log), out, None
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
            want("%s: only the drop list and the token differ from the parent's environment" % name, row["pass"], PASSED)
            want("%s: credentials file in child's config dir" % name, row["cred_exists"], False)
            want("%s: child's config dir is a throwaway agent-home of the run" % name,
                 (row["cfg"].startswith(out + os.sep), os.path.basename(row["cfg"])), (True, "agent-home"))
        want("%s: the names dropped are said on stderr, never their values" % name,
             ("not passed to the session" in text, "CLAUDE_CODE_USE_BEDROCK" in text, "ANTHROPIC_BASE_URL" in text, "example.test" in text, "REFRESH-PARENT" in text),
             (True, True, True, False, False))
        # (d) the value is nowhere it should not be
        want("%s: files under the output dir holding the token" % name, tree_text(out, TOKEN), [])
        want("%s: token on stdout or stderr" % name, TOKEN in text, False)
        want("%s: token on the child's command line" % name, [r for r in rows if any(TOKEN in x for x in r["argv"])], [])
        want("%s: parent's own token on stdout, stderr or in files" % name, (PARENT_TOKEN in text, tree_text(out, PARENT_TOKEN)), (False, []))

    # (d) an agent that runs `env`: stdout, stderr, the hook log, a transcript and a work file all hold the token. The text the harness
    # stores comes out with the placeholder; the agent's own files are kept as they are and nothing of the harness opens its FIFO.
    def world_dirs():
        return [os.path.join(tmp, d) for d in os.listdir(tmp) if d.startswith("auto-mode-2")]

    def drop_worlds():
        for d in world_dirs():
            shutil.rmtree(d, ignore_errors=True)

    outside = os.path.join(tmp, "outside-target.txt")
    put(outside, "outside file with " + TOKEN + "\n", 0o600)
    st_out = os.stat(outside)
    for name, script, which in scripts:
        for keep in (True, False):
            tag = "%s%s" % (name, ", --keep-%s" % ("world" if which == "auto" else "work") if keep else "")
            for noredact in (False, True):
                label = "%s, redaction %s" % (tag, "off (control)" if noredact else "on")
                code, text, rows, out, _ = run(script, which, store_ok, extra_env={"LEAK": "1", "HARDLINK_TARGET": outside}, keep=keep, noredact=noredact)
                files = stored_text(out)
                want("%s: a session ran and the run ended" % label, len(rows) >= 1, True)
                hits = [os.path.relpath(h, out) for h in holding(files, TOKEN)]
                marked = [os.path.relpath(h, out) for h in holding(files, PLACEHOLDER)]
                if noredact:   # control: the same scan, with the redaction off, finds the token in every text the harness stores
                    want("%s: the stored stream or transcript holds the token (gz read decompressed)" % label,
                         any(os.path.basename(h).startswith(("stream", "agent.jsonl")) for h in hits), True)
                    want("%s: the stored stderr holds the token" % label, any(os.path.basename(h) in ("stderr.txt", "agent.err") for h in hits), True)
                    if which == "auto":
                        want("%s: the stored hook log and the stored transcript hold the token" % label, (any(h.endswith("hooks.jsonl") for h in hits), any(h.startswith("transcripts") for h in hits)),
                             (True, True))
                else:
                    want("%s: the stored text holding the token" % label, hits, [])
                    want("%s: token on stdout or stderr of the run" % label, TOKEN in text, False)
                    want("%s: the placeholder is in the stream and the stderr" % label,
                         (any(os.path.basename(h).startswith(("stream", "agent.jsonl")) for h in marked),
                          any(os.path.basename(h) in ("stderr.txt", "agent.err") for h in marked)), (True, True))
                    if which == "auto":
                        want("%s: the placeholder is in the hook log and the transcript" % label,
                             (any(h.endswith("hooks.jsonl") for h in marked), any(h.startswith("transcripts") and h.endswith(".jsonl") for h in marked)), (True, True))
                    if which == "skill" and not keep:
                        want("%s: the transcript is a gzip file holding the placeholder" % label,
                             [m for m in marked if m.endswith("agent.jsonl.gz")] != [], True)
                # the agent's own files are not the harness's to touch: kept as they are, a hard link to a file outside the run too
                kept_roots = [os.path.join(out, "t0", "none", "1", "work")] if which == "skill" else world_dirs()
                if keep:
                    own = [h for k in kept_roots for h in tree_text(k, TOKEN)]
                    want("%s: the file the agent wrote still holds what it wrote (the harness does not rewrite it)" % label,
                         sorted(os.path.basename(h) for h in own), sorted(["hl.txt", "leak.txt"] + (["hooks.jsonl"] if which == "auto" else [])))   # hooks.jsonl: the kept world's own copy of the hook log
                st = os.stat(outside)
                want("%s: the file outside the run, hard-linked by the agent, is untouched" % label,
                     (st.st_ino, st.st_size, st.st_mtime, open(outside).read()), (st_out.st_ino, st_out.st_size, st_out.st_mtime, "outside file with " + TOKEN + "\n"))
                drop_worlds()

    # the same on the timeout path: the session leaked, then outlived --timeout and was killed
    for name, script, which in scripts:
        for noredact in (False, True):
            code, text, rows, out, _ = run(script, which, store_ok, extra_env={"LEAK": "1", "SLEEP": "30"}, noredact=noredact, more=["--timeout", "3"])
            hits = holding(stored_text(out), TOKEN)
            want("%s, timed-out session that leaked, redaction %s: stored text holding the token" % (name, "off (control)" if noredact else "on"),
                 bool(hits), noredact)
            drop_worlds()

    # a transcript the harness cannot store (a FIFO or a link among the session's files): nothing of it is kept under its name, nothing is
    # opened (a FIFO would block), the cell is not-run with one line and the run goes on
    link_target = os.path.join(tmp, "link-target.txt")
    put(link_target, "target holding " + TOKEN + "\n")
    for what in ("TRANSCRIPT_FIFO", "TRANSCRIPT_LINK"):
        code, text, rows, out, _ = run(AUTO, "auto", store_ok, extra_env={"LEAK": "1", what: link_target})
        cells = sorted(os.listdir(os.path.join(out, "transcripts"))) if os.path.isdir(os.path.join(out, "transcripts")) else []
        want("auto_mode, %s among the transcripts: no partial transcript is kept" % what, cells, [])
        want("auto_mode, %s among the transcripts: the cell says why, in one line, and nothing holds the token" % what,
             ("cannot store" in text or "cannot store" in (open(os.path.join(out, "cells.tsv")).read() if os.path.exists(os.path.join(out, "cells.tsv")) else ""),
              holding(stored_text(out), TOKEN)), (True, []))
        drop_worlds()

    # the verdict of a cell is read from the redacted hook log: a denial whose reason holds the token must not put it into cells.tsv
    code, text, rows, out, _ = run(AUTO, "auto", store_ok, extra_env={"DENY_REASON": "1"})
    tsv = open(os.path.join(out, "cells.tsv")).read() if os.path.exists(os.path.join(out, "cells.tsv")) else ""
    want("auto_mode, a denial reason holding the token: the cell was judged from it (denied/classifier, placeholder in the evidence)",
         ("denied/classifier" in tsv, PLACEHOLDER in tsv), (True, True))
    want("auto_mode, a denial reason holding the token: nothing the run stores holds it", holding(stored_text(out), TOKEN), [])
    drop_worlds()

    # text that comes from outside the harness and reaches what it writes and prints: a check that prints a work file the agent wrote the
    # token into, an oracle that errors with it (result.json, the line printed per job), `claude --version` (run.json), an error that names
    # a file called after it (cells.tsv, the summary). All of it passes through one redaction step before it is stored or printed.
    for noredact in (False, True):
        tag = "redaction %s" % ("off (control)" if noredact else "on")
        code, text, rows, out, _ = run(SKILL, "skill", store_ok, extra_env={"LEAK": "1", "VERSION_LEAK": "1"}, tasks="t0,t1", bench_dir=leaky_bench,
                                       noredact=noredact)
        mine = holding(stored_text(out), TOKEN)
        names = sorted(os.path.relpath(h, out) for h in mine)
        res_files = sorted(os.path.join("t%d" % i, "none", "1", "result.json") for i in (0, 1))
        if noredact:   # control: the same runs, the same scan, the new step switched off: result.json, run.json and the printed line hold it
            want("skill_bench, %s: result.json of the check and of the oracle error, and run.json, hold the token" % tag,
                 [n for n in names if n.endswith("result.json") or n == "run.json"], sorted(res_files + ["run.json"]))
            want("skill_bench, %s: the line printed per job holds the token" % tag, TOKEN in text, True)
        else:
            want("skill_bench, %s: nothing the run stores holds the token" % tag, names, [])
            want("skill_bench, %s: nothing printed holds the token" % tag, TOKEN in text, False)
            marked = sorted(os.path.relpath(h, out) for h in holding(stored_text(out), PLACEHOLDER))
            want("skill_bench, %s: the placeholder is in both result.json files and in run.json" % tag,
                 [m for m in marked if m.endswith("result.json") or m == "run.json"], sorted(res_files + ["run.json"]))
            reasons = [json.load(open(os.path.join(out, f))) for f in res_files]
            want("skill_bench, %s: the check's evidence and the oracle's error say what they said, redacted" % tag,
                 (PLACEHOLDER in json.dumps(reasons[0]["checks"]), "oracle crashed" in reasons[1]["invalid_reason"], PLACEHOLDER in reasons[1]["invalid_reason"]),
                 (True, True, True))
    for noredact in (False, True):
        tag = "redaction %s" % ("off (control)" if noredact else "on")
        code, text, rows, out, _ = run(AUTO, "auto", store_ok, extra_env={"LEAK": "1", "VERSION_LEAK": "1", "TRANSCRIPT_FIFO": link_target}, noredact=noredact)
        mine = [os.path.relpath(h, out) for h in holding(stored_text(out), TOKEN)]
        if noredact:
            want("auto_mode, %s: cells.tsv and run.json hold the token (a version line, an error naming a file)" % tag,
                 sorted(n for n in mine if n in ("cells.tsv", "run.json")), ["cells.tsv", "run.json"])
        else:
            want("auto_mode, %s: cells.tsv, run.json and the printed summary do not hold the token" % tag,
                 ([n for n in mine if n in ("cells.tsv", "run.json")], TOKEN in text), ([], False))
            want("auto_mode, %s: the cell reports its harness error, with the placeholder where the name was" % tag,
                 ("harness error" in open(os.path.join(out, "cells.tsv")).read(), PLACEHOLDER in open(os.path.join(out, "cells.tsv")).read()), (True, True))
        drop_worlds()

    # (f) skill_bench jobs have a config dir of their own: job 1 writes a settings file and a marker there, job 2 must not see them
    for workers in ("1", "2"):
        code, text, rows, out, _ = run(SKILL, "skill", store_ok, extra_env={"WRITE_SETTINGS": "1"}, tasks="t0,t1", workers=workers)
        want("skill_bench, %s worker(s): both jobs ran" % workers, len(rows), 2)
        want("skill_bench, %s worker(s): no job saw settings or a marker another job wrote" % workers,
             sorted((r["seen_settings"], r["seen_marker"]) for r in rows), [('{"model": "sonnet"}', False)] * 2)
        want("skill_bench, %s worker(s): each job had its own config dir" % workers, len({r["cfg"] for r in rows}), 2)

    # (b) the key missing: no session starts, one line names the key and the fix
    for label, store in (("key absent", store_nokey), ("key empty", store_empty), ("no store", os.path.join(tmp, "missing.json"))):
        for name, script, which in scripts:
            code, text, rows, out, _ = run(script, which, store)
            want("%s, %s: exit" % (name, label), code != 0, True)
            want("%s, %s: child started" % (name, label), len(rows) > 0, False)
            want("%s, %s: names the key and the fix" % (name, label), (KEY in text, "claude setup-token" in text, "Traceback" in text), (True, True, False))
            want("%s, %s: the parent's token is not printed" % (name, label), PARENT_TOKEN in text, False)

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
    put(store_nul, json.dumps({KEY: "tok-BADVALUE-0123456\x00x"}))
    store_sur = os.path.join(tmp, "store-surrogate.json")
    put(store_sur, json.dumps({KEY: "tok-BADVALUE-0123456\ud800x"}))
    store_sp = os.path.join(tmp, "store-space.json")
    put(store_sp, json.dumps({KEY: "tok-BADVALUE 0123456789"}))
    store_short = os.path.join(tmp, "store-short.json")
    put(store_short, json.dumps({KEY: "1"}))
    store_19 = os.path.join(tmp, "store-19.json")
    put(store_19, json.dumps({KEY: "tok-BADVALUE-01234"}))
    store_long = os.path.join(tmp, "store-long.json")
    put(store_long, json.dumps({KEY: "tok-BADVALUE-" + "a" * 4084}))
    store_huge = os.path.join(tmp, "store-huge.json")
    put(store_huge, json.dumps({KEY: "tok-BADVALUE-" + "a" * 300000}))
    store_utf = os.path.join(tmp, "store-nonascii.json")
    put(store_utf, json.dumps({KEY: "tok-BADVALUE-caf\u00e9-012345"}))
    store_deep = os.path.join(tmp, "store-deep.json")
    put(store_deep, "[" * 200000)
    store_000 = os.path.join(tmp, "store-000.json")
    put(store_000, json.dumps({KEY: TOKEN}), 0o000)
    variants = [("missing file", os.path.join(tmp, "missing.json"), "does not exist"), ("a directory", store_dir, "is a directory"),
                ("not JSON", store_bin, "not valid JSON"), ("nested too deep for the parser", store_deep, "not valid JSON"), ("a JSON array", store_arr, "not an object"), ("key absent", store_nokey, "is not in the store"),
                ("key empty", store_empty, "is empty"), ("key not a string", store_int, "not a string"),
                ("NUL in the value", store_nul, "not a plausible token"), ("lone surrogate in the value", store_sur, "not a plausible token"),
                ("space inside the value", store_sp, "not a plausible token"), ("one character", store_short, "not a plausible token"),
                ("19 characters", store_19, "not a plausible token"), ("4097 characters", store_long, "not a plausible token"),
                ("300000 characters", store_huge, "not a plausible token"), ("non-ASCII", store_utf, "not a plausible token")]
    if os.geteuid() != 0:
        variants.append(("unreadable file", store_000, "cannot be read"))
    else:
        not_run.append("unreadable store case -> NOT RUN, NOT ARMED: running as root, mode 000 is readable")
    for label, store, cause in variants:
        for name, script, which in scripts:
            code, text, rows, out, _ = run(script, which, store)
            want("%s, store %s: exit (the whole run, not 0 with invalid jobs)" % (name, label), code != 0, True)
            want("%s, store %s: child started" % (name, label), len(rows), 0)
            line = " ".join(l for l in text.splitlines() if "no measurement login" in l)   # the error line itself, not the redirect notice
            want("%s, store %s: says what failed, names the store, the key and the fix" % (name, label),
                 (cause in line, store in line, KEY in line, "claude setup-token" in line, "Traceback" in text), (True, True, True, True, False))
            want("%s, store %s: no part of the bad value is echoed" % (name, label), "BADVALUE" in text or TOKEN in text or "a" * 50 in text, False)
            want("%s, store %s: one error line" % (name, label), len([l for l in text.splitlines() if "no measurement login" in l]), 1)
    for name, script, which in scripts:
        code, text, rows, out, _ = run(script, which, store_ok)
        want("%s: a redirected store is said on stderr, with its path, never the value" % name,
             (("redirected by FORGE_SECRETS_FILE to %s" % store_ok) in text, TOKEN in text), (True, False))
    # a config dir whose `.credentials.json` cannot be removed (a directory): one line, no traceback, no session, exit non-zero
    code, text, rows, out, _ = run(AUTO, "auto", store_ok, pre=lambda d: os.makedirs(os.path.join(d, ".credentials.json", "sub")))
    want("auto_mode, a directory named .credentials.json: refused with one line",
         (code != 0, len(rows), "Traceback" in text, ".credentials.json" in text), (True, 0, False, True))
    # skill_bench makes a fresh config dir per job; when one cannot be prepared the whole run ends, one line, non-zero, no further job
    put(os.path.join(tmp, "failclean.py"), '''
import os, runpy, sys
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.path.dirname(script))
import measure_login
def boom(d):
    raise measure_login.LoginError("cannot remove %s/.credentials.json (toy failure): a login file is left in the throwaway config dir. No session was started." % d)
measure_login.clean_config_dir = boom
runpy.run_path(script, run_name="__main__")
''')
    counter[0] += 1
    fout = os.path.join(tmp, "out-%d" % counter[0])
    flog = os.path.join(tmp, "fake-%d.log" % counter[0])
    r = subprocess.run([sys.executable, os.path.join(tmp, "failclean.py"), SKILL, "run", "--bench", bench, "--claude-bin", fake, "--sandbox", "none",
                        "--out", fout, "--k", "1", "--tasks", "t0,t1", "--arm", "none", "--workers", "1"],
                       capture_output=True, text=True, env=env_for(store_ok, flog), timeout=300, stdin=subprocess.DEVNULL)
    want("skill_bench, a job's config dir cannot be prepared: the whole run ends with one line, non-zero, no session",
         (r.returncode != 0, len(log_rows(flog)), "Traceback" in r.stdout + r.stderr, "toy failure" in r.stdout + r.stderr), (True, 0, False, True))

    # no private path or ticket id in an engine file: every path-like reference resolves, and no ticket-shaped id; the root README says the
    # key is needed
    import re
    for rel in ("scripts/bench/measure_login.py", "scripts/bench/auto_mode.py", "scripts/bench/skill_bench.py", "tests/test_measure_login.py",
                "benchmarks/skill-bench/README.md"):
        body = open(os.path.join(sandbox.FORGE, rel)).read()
        refs = {m.rstrip(".,);:") for m in re.findall(r"(?<![\w/.-])((?:scripts|tests|benchmarks|docs|forge|plugins|hooks|bin)/[A-Za-z0-9_./-]+)", body)}
        refs = {r for r in refs if "<" not in r and "*" not in r and not r.endswith("/")}
        want("%s: every path it names exists" % rel, sorted(r for r in refs if not os.path.exists(os.path.join(sandbox.FORGE, r))), [])
        want("%s: no ticket-shaped id" % rel, sorted(set(re.findall(r"\b[A-Z]{2,5}-[0-9]+\b", body)) - {"SHA-256", "UTF-8", "ISO-8601"}), [])
    want("README.md quick-start names the key", KEY in open(os.path.join(sandbox.FORGE, "README.md")).read(), True)

    # (c) a leftover credentials link and file in the throwaway dir
    target = os.path.join(tmp, "target-creds.json")
    put(target, '{"toy": "target"}', 0o600)
    os.utime(target, (1_000_000_000, 1_000_000_000))
    st0 = os.stat(target)
    for name, script, which in scripts[:1]:   # skill_bench's config dir is made fresh per job: (f)
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
        # text the harness stores: replaced (also the JSON-escaped form of a value with a quote or a backslash), written as a new file
        weird = 'tok-"quoted"\\back-0123456789'
        want("helper: redact_text", (ml.redact_text("a " + TOKEN + " b", TOKEN), ml.redact_text(None, TOKEN)), ("a " + PLACEHOLDER + " b", ""))
        want("helper: the JSON form of a value with a quote and a backslash is replaced too",
             (weird in ml.redact_text(json.dumps({"t": weird}), weird), PLACEHOLDER in ml.redact_text(json.dumps({"t": weird}), weird)), (False, True))
        want("helper: redact_text keeps bytes that are not UTF-8", ml.redact_text("\udcff" + TOKEN, TOKEN), "\udcff" + PLACEHOLDER)
        adir = os.path.join(tmp, "atomic-unit")
        os.makedirs(adir)
        final = os.path.join(adir, "stored.txt")
        put(final, "old content")

        class Killed(BaseException):
            pass

        def die(*a, **k):
            raise Killed()
        real_replace = os.replace
        os.replace = die   # the process dies between the write and the rename
        try:
            try:
                ml.write_atomic(final, b"new content with " + TOKEN.encode())
            except Killed:
                pass
            try:
                ml.write_atomic(os.path.join(adir, "fresh.txt"), b"x")
            except Killed:
                pass
        finally:
            os.replace = real_replace
        want("helper: a kill between write and rename leaves the old file whole and no file under a new name",
             (open(final).read(), os.path.exists(os.path.join(adir, "fresh.txt")), sorted(os.listdir(adir))), ("old content", False, ["stored.txt"]))
        ml.write_redacted(final, "line " + TOKEN, TOKEN)
        want("helper: write_redacted stores the redacted text as a new file", (open(final).read(), stat.S_IMODE(os.stat(final).st_mode)), ("line " + PLACEHOLDER, 0o644))
        src_f = os.path.join(adir, "src.jsonl")
        put(src_f, "a " + TOKEN)
        ml.copy_redacted(src_f, os.path.join(adir, "dst.jsonl"), TOKEN)
        want("helper: copy_redacted stores a redacted copy and leaves the source", (open(os.path.join(adir, "dst.jsonl")).read(), open(src_f).read()),
             ("a " + PLACEHOLDER, "a " + TOKEN))
        os.symlink(src_f, os.path.join(adir, "lnk"))
        os.mkfifo(os.path.join(adir, "fifo"))
        for nm in ("lnk", "fifo"):   # a link or a special file is refused without being opened (a FIFO would block): in a child with a time limit
            code_snip = ("import sys; sys.path.insert(0, %r); import measure_login as ml\n"
                         "try:\n    ml.copy_redacted(%r, %r, %r)\n    print('ACCEPTED')\n"
                         "except ml.LoginError as e:\n    print('REFUSED', e)\n"
                         % (BENCH_DIR, os.path.join(adir, nm), os.path.join(adir, "out-" + nm), TOKEN))
            try:
                r = subprocess.run([sys.executable, "-c", code_snip], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
                got = (r.stdout.startswith("REFUSED"), "not a regular file" in r.stdout, len(r.stdout.strip().splitlines()), os.path.exists(os.path.join(adir, "out-" + nm)))
            except subprocess.TimeoutExpired:
                got = "hung (it opened the %s)" % nm
            want("helper: copy_redacted refuses a %s with one line and stores nothing" % nm, got, (True, True, 1, False))
        parent2 = dict(PASSED, A="1", HOME="/srv/toy-home", PATH="/srv/bin")
        parent2.update({k: "x" for k in DROPPED})
        want("helper: the child environment is the parent's minus the drop list plus the token",
             ml.child_env(parent2, secrets_file=sec), dict(PASSED, A="1", HOME="/srv/toy-home", PATH="/srv/bin", CLAUDE_CODE_OAUTH_TOKEN=TOKEN))
        want("helper: the drop list is the one this test states", sorted(set(ml.DROPPED) - {"CLAUDE_CODE_OAUTH_TOKEN"}), sorted(set(DROPPED)))
        for bad_store, why in ((store_short, "plausible"), (store_huge, "plausible"), (store_nokey, "not in the store"), (os.path.join(tmp, "missing.json"), "does not exist")):
            try:
                ml.child_env({}, secrets_file=bad_store)
                failures.append("helper: no refusal for %s" % os.path.basename(bad_store))
            except ml.LoginError as e:   # the exception text itself names the store (the output of a run also holds the redirect notice)
                want("helper: the refusal for %s names the cause and the store path" % os.path.basename(bad_store), (why in str(e), bad_store in str(e)), (True, True))
        d = os.path.join(tmp, "cfgdir")
        os.makedirs(d)
        os.symlink(target, os.path.join(d, ".credentials.json"))
        ml.clean_config_dir(d)
        want("helper: clean_config_dir removes a link and keeps its target", (os.path.lexists(os.path.join(d, ".credentials.json")), os.path.exists(target)), (False, True))

    import skill_bench as sb  # noqa: E402
    import auto_mode as am  # noqa: E402
    if ml:   # a config dir that cannot be made (its parent is a regular file): LoginError with one line, never a bare OSError (a traceback)
        blocker = os.path.join(tmp, "blocker")
        put(blocker, "x")
        for modname, mod in (("skill_bench", sb), ("auto_mode", am)):
            try:
                mod.agent_home(os.path.join(blocker, "sub"))
                failures.append("%s.agent_home: no error for a parent that is a file" % modname)
            except ml.LoginError as e:
                want("%s.agent_home: the error is one line naming the dir" % modname, (os.path.join(blocker, "sub") in str(e), "\n" in str(e)), (True, False))
            except OSError as e:
                failures.append("%s.agent_home: a bare %s instead of LoginError" % (modname, type(e).__name__))
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
    try:
        main()
    except SystemExit:
        raise
    except BaseException:   # a crash must not hide the failures found before it
        for msg in failures:
            print("FAIL", msg)
        print("%d failure(s) before the crash" % len(failures))
        raise
