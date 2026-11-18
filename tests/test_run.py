#!/usr/bin/env python3
"""`forge run @NAME "PROMPT"` (forge/run.py): one headless session of this project with a session profile, started from a
terminal or by an agent from its Bash tool; stdout carries only the final answer.

The world is test_profiles' (an engine copy, a toy HOME, the project `multi` with the profiles `toy-b` and `list`, `none` without
`profiles`, `frozen-p`) and a PATH that holds only a fake directory (claude, python3, git; ORDERS 10). The fake claude dumps its
argv, its stdin, its environment and its cwd, prints FAKE_STDOUT (a JSON result by default) and exits FAKE_EXIT.

Cases: 1 the child gets `--model sonnet` when none is given, the caller's otherwise, once; 2 stdout is the answer and only it
(--json: the whole JSON), stderr one line `profile P session ID cost USD`; 3 the exit code is the child's, and a child that exits 0
with `is_error`, or with output that is no result, is exit 1 (never an error counted as success); 4 the refusals (unknown name,
frozen, no profiles, bare @, not an @, no prompt, an empty prompt, no project, a --cwd that is no folder, claude not on PATH) are
exit 2 (127 for claude) with `forge start`'s wording, the child not run and nothing written; 5 the child gets the profile flags
`forge start @NAME` gives for the same profile (settings and servers files byte for byte), and no wider permissions: no
--permission-mode unless asked, never the skip flag; 6 the session record: profile, project, print, launcher pid, `parent` only
when CLAUDE_CODE_SESSION_ID is set, keyed by the --session-id the child got; 7 the prompt reaches claude on stdin, verbatim, never
through a shell and never as an argument (a prompt that starts with `-` is not a flag); 8 --cwd: the child runs there and the project
is that folder's; 9 FORGE_PROFILE and FORGE_PROJECT reach the child, the caller's FORGE_SESSION does not.

Written first and run against the code that had `forge start @NAME` and no `run` subcommand: 47 FAIL lines (the exit was 2, "invalid
choice: 'run'"), the first "FAIL 1: no --model given: the child gets sonnet, once: None, want ['--model', 'sonnet']" and
"FAIL 3: the child's exit code is ours: 2, want 7".
Negative controls, in MUTANTS below: each mutates the engine copy, and the case it names must fail on it (main fails otherwise). The
first line each produced, run against forge/run.py as committed:
  no-model     the default `sonnet` not passed      -> "FAIL 1: no --model given: the child gets sonnet, once: None, want ['--model', 'sonnet']"
  err-as-ok    is_error not looked at               -> "FAIL 3: exit 0 with is_error: exit 1, nothing on stdout, the reason on stderr: (0, '\n', False), want (1, '', True)"
  code-lost    the child's exit code replaced by 0  -> "FAIL 3: the child's exit code is ours: 0, want 7"
  no-parent    `parent` not recorded                -> "FAIL 6: the record names the parent session: None, want outer-session-7"
  in-argv      the prompt as an argument, not stdin -> "FAIL 5: the child gets the profile flags forge start gives, in the same order: ['--', 'do the thing', ..." (and 7)
  skip-perms   the skip flag added to the child     -> "FAIL 5: no wider permissions than forge start gives: ['--dangerously-skip-permissions'], want []"
  wording      the refusals worded `forge start`    -> "FAIL 4: a project without profiles: one line with the reason 'declares no profiles', from forge run: (1, True, False), want (1, True, True)"
  cwd-ignored  --cwd not entered                    -> "FAIL 8: --cwd: the child runs there and the project is that folder's: (2, None, None), want (0, '.../projects/multi', 'multi')"
  noise        the answer printed with a banner     -> "FAIL 2: stdout is the answer and only it: (0, 'forge run: the answer\n'), want (0, 'the answer\n')"
"""
import json
import os
import shutil
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
import test_profiles as tp  # noqa: E402

FAKE = """#!%s
import json, os, sys
with open(os.environ["FAKE_OUT"], "w") as fh:
    json.dump({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "env": dict(os.environ), "cwd": os.getcwd(), "ppid": os.getppid()}, fh)
sys.stdout.write(os.environ.get("FAKE_STDOUT", json.dumps({"type": "result", "subtype": "success", "is_error": False,
                 "result": "the answer", "session_id": "from-the-child", "total_cost_usd": 0.0123})))
sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
OK_JSON = {"type": "result", "subtype": "success", "is_error": False, "result": "the answer", "session_id": "from-the-child",
           "total_cost_usd": 0.0123}
# name: (file in the engine copy, the text that is there, what replaces it, the label of the case that must fail)
MUTANTS = {
    "no-model": ("forge/run.py", 'a.model or "sonnet"', 'a.model or None', "1: no --model given"),
    "err-as-ok": ("forge/run.py", 'doc.get("is_error")', 'False', "3: exit 0 with is_error"),
    "code-lost": ("forge/run.py", "code = launch._run(", "code = 0 * launch._run(", "3: the child's exit code is ours"),
    "no-parent": ("forge/run.py", 'os.environ.get("CLAUDE_CODE_SESSION_ID")', 'None', "6: the record names the parent session"),
    "in-argv": ("forge/run.py", 'argv = flags + ["--session-id", sid, "--model", model]', 'argv = ["--", a.prompt] + flags + ["--session-id", sid, "--model", model]',
                "7: the prompt arrives on stdin"),  # fails 5 and 7
    "skip-perms": ("forge/run.py", '"--output-format", "json", "-p"', '"--dangerously-skip-permissions", "--output-format", "json", "-p"',
                   "5: no wider permissions"),
    "wording": ("forge/run.py", 'WHO = "forge run"', 'WHO = "forge start"', "4: a project without profiles: one line"),
    "cwd-ignored": ("forge/run.py", "os.chdir(a.cwd)  # the project", "pass  # the project", "8: --cwd: the child runs there"),
    "noise": ("forge/run.py", "print(answer)", 'print("forge run: " + answer)', "2: stdout is the answer"),
}
SENTINEL_PROMPT = "line one\n$(touch {sentinel}); `touch {sentinel}`; 'quoted' \"double\" \\ ; & | > <\nline three é"


def jload(text):
    """The JSON object in `text`, or None: a missing document is a FAIL line, never a traceback."""
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def cases(mutate=None):
    """The failure lines of every case, in a world whose engine copy has the one mutation `mutate` (a MUTANTS row) or none."""
    failures = []

    def want(label, got, expected):
        if got != expected:
            failures.append("FAIL %s: %s, want %s" % (label, got, expected))

    w = tp.World(["multi", "none", "frozen-p"], skills=tp.SKILLS + ("toy-other",), mutate=mutate and mutate[:3])
    tp.write_json(os.path.join(w.forge, "config", "mcp-registry.json"),
                  {"servers": {"toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}}}})
    home, multi = w.home, w.pp("multi")
    tp.write_json(os.path.join(home, ".claude", "settings.json"), {"enabledPlugins": {"p-def@m": True, "toy-plugin@x": True}})
    tp.write_json(os.path.join(home, ".claude.json"), {"projects": {}, "mcpServers": {}})
    sandbox.git(multi, "add", "-A")
    sandbox.git(multi, "commit", "-q", "--allow-empty", "-m", "c")
    fakebin = os.path.join(w.root, "fakebin")
    os.makedirs(fakebin)
    with open(os.path.join(fakebin, "claude"), "w") as fh:
        fh.write(FAKE % sys.executable)
    os.chmod(os.path.join(fakebin, "claude"), 0o755)
    os.symlink(sys.executable, os.path.join(fakebin, "python3"))
    os.symlink(shutil.which("git"), os.path.join(fakebin, "git"))
    dumps = sandbox.mkdtemp("forge-dumps-")
    state = os.path.join(home, ".local", "state", "forge")
    n = [0]

    def forge(verb, args, cwd=multi, extra=None, fake=True):
        """(exit code, stdout, stderr, the fake's dump or None) of `forge VERB ARGS`."""
        n[0] += 1
        out = os.path.join(dumps, "dump-%d.json" % n[0])
        e = sandbox.bare_env(home, w.root, **dict(dict(FAKE_OUT=out), **(extra or {})))
        e["PATH"] = fakebin if fake else os.path.join(w.root, "nobin")
        r = subprocess.run([sys.executable, os.path.join(w.forge, "bin", "forge"), verb] + args, cwd=cwd, env=e, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=120)
        dump = None
        if os.path.exists(out):
            with open(out) as fh:
                dump = json.load(fh)
        return r.returncode, r.stdout, r.stderr, dump

    def run(args, **k):
        return forge("run", args, **k)

    def flag(argv, name):
        return argv[argv.index(name) + 1] if argv and name in argv and argv.index(name) + 1 < len(argv) else None

    def read(p):
        try:
            with open(p) as fh:
                return fh.read()
        except (OSError, TypeError):
            return None

    def tree():
        return w.files("")

    def records():
        d = os.path.join(state, "profile-sessions")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    # 1 --model: always passed, `sonnet` when the caller gave none.
    code, so, se, d = run(["@toy-b", "do the thing"])
    argv = d and d["argv"]
    want("1: no --model given: the child gets sonnet, once", argv and [a for a in argv if a == "--model"] + [flag(argv, "--model")],
         ["--model", "sonnet"])
    code, so, se, d = run(["@toy-b", "do the thing", "--model", "haiku"])
    argv = d and d["argv"]
    want("1: --model haiku: the child gets haiku, once", argv and ([a for a in argv if a == "--model"], flag(argv, "--model")), (["--model"], "haiku"))
    code, so, se, d = run(["--model", "opus", "@toy-b", "do the thing"])
    want("1: --model before the name works too", d and flag(d["argv"], "--model"), "opus")
    want("1: the child is headless and asks for JSON", d and ("-p" in d["argv"], flag(d["argv"], "--output-format")), (True, "json"))

    # 2 stdout is the answer only; --json the whole document; stderr one line.
    code, so, se, d = run(["@toy-b", "do the thing"])
    want("2: stdout is the answer and only it", (code, so), (0, "the answer\n"))
    sid = d and flag(d["argv"], "--session-id")
    want("2: stderr is one line: profile, session, cost", se, "profile toy-b session from-the-child cost 0.0123 USD\n")
    code, so, se, d = run(["@toy-b", "do the thing", "--json"])
    want("2: --json: stdout is the whole document", (code, jload(so) or so), (0, OK_JSON))
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_STDERR="child noise\n"))
    want("2: the child's own stderr is not on stdout", (so, "child noise" in se), ("the answer\n", True))

    # 3 the exit code is the child's; an error of the child is never a success.
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_EXIT="7"))
    want("3: the child's exit code is ours", code, 7)
    bad = dict(OK_JSON, is_error=True, subtype="error_max_turns", result="")
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_STDOUT=json.dumps(bad)))
    want("3: exit 0 with is_error: exit 1, nothing on stdout, the reason on stderr", (code, so, "error_max_turns" in se), (1, "", True))
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_STDOUT="not json at all"))
    want("3: exit 0 with output that is no result: exit 1, nothing on stdout", (code, so, "result" in se), (1, "", True))
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_STDOUT=""))
    want("3: exit 0 with no output: exit 1", code, 1)
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(FAKE_EXIT="3", FAKE_STDOUT=json.dumps(dict(bad, result="boom"))))
    want("3: a failing child with a result: its code, no answer on stdout, the text on stderr", (code, so, "boom" in se), (3, "", True))
    code, so, se, d = run(["@toy-b", "do the thing", "--json"], extra=dict(FAKE_STDOUT=json.dumps(bad)))
    want("3: --json with is_error: the document is printed and the exit is 1", (code, (jload(so) or {}).get("subtype")), (1, "error_max_turns"))

    # 4 refusals: exit 2, one line with forge start's wording, the child not run, nothing written.
    for label, args, cwd, why in (("a project without profiles", ["@toy-b", "hi"], w.pp("none"), "declares no profiles"),
                                  ("a frozen project", ["@list", "hi"], w.pp("frozen-p"), "frozen"),
                                  ("an unknown name", ["@toy-c", "hi"], multi, "toy-b"),
                                  ("a folder that is no project", ["@toy-b", "hi"], home, "not inside a project"),
                                  ("a bare @", ["@", "hi"], multi, "forge list @"),
                                  ("a name with no @", ["toy-b", "hi"], multi, "is not a profile")):
        before = tree()
        code, so, se, d = run(args, cwd=cwd)
        want("4: %s: (exit, child not run, nothing written, stdout)" % label, (code, d, tree() == before, so), (2, None, True, ""))
        want("4: %s: one line with the reason %r, from forge run" % (label, why),
             (len(se.strip().splitlines()), why in se, se.startswith("! forge run")), (1, True, True))
    for args, cwd in ((["@toy-b", "hi"], w.pp("none")), (["@list", "hi"], w.pp("frozen-p")), (["@toy-c", "hi"], multi), (["@toy-b", "hi"], home)):
        _, _, start_err, _ = forge("start", args[:1], cwd=cwd)
        _, _, run_err, _ = run(args, cwd=cwd)
        want("4: %s: the reason is forge start's, word for word" % args[:1], run_err.replace("forge run", "forge start", 1), start_err)
    before = tree()
    for label, args in (("no prompt", ["@toy-b"]), ("an empty prompt", ["@toy-b", ""]), ("a blank prompt", ["@toy-b", "  \n "])):
        code, so, se, d = run(args)
        want("4: %s: exit 2, usage or reason, child not run, nothing written" % label,
             (code, d, tree() == before, "forge run" in se and ("usage" in se or "prompt" in se)), (2, None, True, True))
    code, so, se, d = run(["@toy-b", "hi"], fake=False)
    want("4: claude not on PATH: exit 127 naming it, nothing written", (code, "claude" in se and "PATH" in se, tree() == before), (127, True, True))
    shut = os.path.join(w.root, "shut")
    os.mkdir(shut, 0o000)  # a folder that exists and cannot be entered: one line, never a traceback (red before the guard: "(1, ... Traceback")
    code, so, se, d = run(["@toy-b", "hi", "--cwd", shut])
    os.chmod(shut, 0o700)
    want("4: a --cwd that cannot be entered: exit 2, one line, no traceback", (code, d, len(se.strip().splitlines()), "Traceback" in se), (2, None, 1, False))
    code, so, se, d = run(["@toy-b", "hi", "--cwd", os.path.join(w.root, "nothing-here")])
    want("4: a --cwd that is no folder: exit 2", (code, d, "--cwd" in se), (2, None, True))

    # 5 the same profile flags as forge start, and no wider permissions.
    code, _, _, started = forge("start", ["@toy-b", "-p", "hi"])
    start_settings, start_mcp = (started["argv"][started["argv"].index(f) + 1] for f in ("--settings", "--mcp-config"))
    start_files = (read(start_settings), read(start_mcp))
    start_head = started["argv"][:started["argv"].index("--settings") + 2]
    code, so, se, d = run(["@toy-b", "do the thing"])
    argv = d and d["argv"]
    child_files = (read(flag(argv, "--settings")), read(flag(argv, "--mcp-config")))
    want("5: the child gets the profile flags forge start gives, in the same order", argv and argv[:len(start_head)], start_head)
    want("5: its settings and servers files are forge start's, byte for byte, and are not empty", (child_files == start_files, all(child_files)), (True, True))
    want("5: no wider permissions than forge start gives", argv and [a for a in argv if a in ("--dangerously-skip-permissions", "--permission-mode", "--allowedTools",
         "--allowed-tools", "--allow-dangerously-skip-permissions")], [])
    want("5: the profile's own permissions are in --settings", json.loads(child_files[0] or "{}").get("permissions"), {"allow": ["Read"]})
    code, so, se, d = run(["@toy-b", "do the thing", "--permission-mode", "plan"])
    want("5: --permission-mode is passed when asked", d and flag(d["argv"], "--permission-mode"), "plan")
    code, so, se, d = run(["@code", "do the thing"])
    want("5: the default label: no profile flags, the model still passed", d and ([f for f in ("--settings", "--mcp-config") if f in d["argv"]], flag(d["argv"], "--model")),
         ([], "sonnet"))

    # 6 the session record.
    before = set(records())
    code, so, se, d = run(["@toy-b", "do the thing"], extra=dict(CLAUDE_CODE_SESSION_ID="outer-session-7"))
    sid = d and flag(d["argv"], "--session-id")
    try:
        uuid.UUID(sid)
        valid = True
    except (ValueError, TypeError, AttributeError):
        valid = False
    want("6: the child gets a --session-id that is a uuid", valid, True)
    rec = json.loads(read(os.path.join(state, "profile-sessions", "%s.json" % sid)) or "null")
    want("6: the record: profile, project, print, a launcher pid", rec and (rec["profile"], rec["project"], rec.get("print"), isinstance(rec["launcher_pid"], int)),
         ("toy-b", "multi", True, True))
    want("6: the record names the parent session", rec and rec.get("parent"), "outer-session-7")
    want("6: the record's launcher is the child's parent", rec and d and rec["launcher_pid"], d and d["ppid"])
    code, so, se, d = run(["@toy-b", "do the thing"])
    rec = json.loads(read(os.path.join(state, "profile-sessions", "%s.json" % (d and flag(d["argv"], "--session-id")))) or "null")
    want("6: with no outer session there is no parent", rec and "parent" in rec, False)
    want("6: each run writes one record", len(set(records()) - before), 2)

    # 7 the prompt: stdin, verbatim, no shell.
    sentinel = os.path.join(w.root, "pwned")
    prompt = SENTINEL_PROMPT.format(sentinel=sentinel)
    code, so, se, d = run(["@toy-b", prompt])
    want("7: the prompt arrives on stdin, verbatim, and not in argv", d and (d["stdin"], any("touch" in a or "line one" in a for a in d["argv"])), (prompt, False))
    want("7: no shell ran what the prompt says", os.path.exists(sentinel), False)
    code, so, se, d = run(["@toy-b", "--", "--help me, I start with dashes"])
    want("7: a prompt that starts with dashes is a prompt, not a flag", d and (d["stdin"], "--help" in " ".join(d["argv"])), ("--help me, I start with dashes", False))
    code, so, se, d = run(["@toy-b", "-1 is a number"])
    want("7: a prompt with a dash and a space is a prompt", (code, d and d["stdin"]), (0, "-1 is a number"))

    # 8 --cwd.
    code, so, se, d = run(["@toy-b", "hi", "--cwd", multi], cwd=home)
    want("8: --cwd: the child runs there and the project is that folder's", (code, d and d["cwd"], d and d["env"].get("FORGE_PROJECT")), (0, os.path.realpath(multi), "multi"))
    code, so, se, d = run(["@toy-b", "hi"])
    want("8: without --cwd the child runs in the current folder", d and d["cwd"], os.path.realpath(multi))

    # 9 the environment.
    code, so, se, d = run(["@toy-b", "hi"], extra=dict(FORGE_SESSION="outer-forge-session", FORGE_LAUNCHER_PID="1"))
    sid = d and flag(d["argv"], "--session-id")
    want("9: FORGE_PROFILE and FORGE_PROJECT reach the child", d and (d["env"].get("FORGE_PROFILE"), d["env"].get("FORGE_PROJECT")), ("toy-b", "multi"))
    want("9: the child's FORGE_SESSION is its own, not the caller's (a `forge switch` in it must not restart the caller)",
         d and (d["env"].get("FORGE_SESSION"), d["env"].get("FORGE_LAUNCHER_PID") != "1"), (sid, True))
    switch_dir = os.path.join(state, "profile-switch")
    code, so, se, d = forge("switch", ["@list"], cwd=multi, extra=dict(FORGE_SESSION=sid or "none", FORGE_LAUNCHER_PID=str(os.getpid())))
    want("9: forge switch in a finished forge run session is refused and writes no request", (code, os.path.isdir(switch_dir) and os.listdir(switch_dir)), (2, False))
    return failures


def main():
    try:
        failures = cases()
        for name, row in MUTANTS.items():
            fails = cases(row)
            if not any(f.startswith("FAIL " + row[3]) for f in fails):
                failures.append("FAIL control %s: the mutant did not fail the case %r (it failed: %s)" % (name, row[3], [f[:60] for f in fails]))
        if failures:
            print("\n".join(failures))
            return 1
        print("ok: run (%d mutants seen failing)" % len(MUTANTS))
        return 0
    finally:
        sandbox.cleanup()


if __name__ == "__main__":
    sys.exit(main())
