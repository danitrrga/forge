#!/usr/bin/env python3
"""`forge start NAME [ARGS...]` (forge/launch.py): claude started with the environment a named launcher declares in
config/forge.json (`launchers`: {name: {"env": {VAR: value}}}), so one kind of session can carry a variable (the
keepwarm switch of an orchestrator) without every session carrying it.

The command was `forge launch` until it was renamed `forge start`; the red below is from when it was written.
Written first and run against the code that did not yet have the subcommand: 24 FAIL lines, the first "FAIL exit of a
launch (the fake exits 0): (2, \"usage: forge [-h] ... forge: error: argument cmd: invalid choice: 'launch'", then "env
reaches claude: CACHE_TAX_AUTOWARM: None, want on" and "claude not on PATH: (exit, says so): (2, False), want (127, True)"
(the cases that expect exit 2 pass by accident there, which is why each also checks the message). Negative control: with
the env merge in forge/launch.py broken (`env = dict(os.environ)`) the run fails "FAIL env reaches claude:
CACHE_TAX_AUTOWARM: None, want on" and "FAIL the other launcher: its variable: None, want x". The mutation is not kept.

The world is a toy: a forge.json under a temp dir that lib.SETTINGS points at (in the child process only), a fake
`claude` that writes its argv and two variables to a file, and a PATH that holds only the fake's directory (ORDERS 10: a
"claude missing" case behind /usr/bin would find the real one). The command runs in a child because it replaces the process.
Cases: the launcher's variable reaches claude; the caller's own variables stay; a variable of another launcher is not
added; every argument after NAME, flags included, arrives untouched and in order; no name lists the launchers (and says
so when there are none); an unknown name is exit 2 naming the known ones; a malformed `launchers` (not an object, a
launcher not an object, `env` not an object, a value that is not a string, a key forge does not know) is exit 2 naming
the key; claude not on PATH is exit 127."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures = []
CHILD = ("import sys; from forge import cli, lib; lib.SETTINGS = sys.argv[1]; sys.exit(cli.main(sys.argv[2:]))")
FAKE = "#!%s\nimport json, os, sys\njson.dump({'argv': sys.argv[1:], 'orq': os.environ.get('CACHE_TAX_AUTOWARM'), " \
       "'other': os.environ.get('OTHER_VAR'), 'kept': os.environ.get('CALLER_VAR')}, open(sys.argv[0] + '.out', 'w'))\n" % sys.executable
LAUNCHERS = {"orq": {"env": {"CACHE_TAX_AUTOWARM": "on"}}, "plain": {"env": {"OTHER_VAR": "x"}},
             "tok": {"env": {"SECRET_VAR": "hunter2"}}}


def want(label, got, expected):
    if got != expected:
        failures.append("%s: %s, want %s" % (label, got, expected))


def launch(tmp, launchers, args, with_claude=True):
    """(exit code, stdout, stderr, what the fake claude recorded or None)."""
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    fake = os.path.join(bin_dir, "claude")
    if with_claude:
        with open(fake, "w") as fh:
            fh.write(FAKE)
        os.chmod(fake, 0o755)
    doc = {"integrations": {}}
    if launchers is not None:
        doc["launchers"] = launchers
    settings = os.path.join(tmp, "forge.json")
    with open(settings, "w") as fh:
        json.dump(doc, fh)
    env = {"PATH": bin_dir, "HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1", "CALLER_VAR": "mine"}
    r = subprocess.run([sys.executable, "-c", CHILD, settings] + args, cwd=sandbox.FORGE, env=env,
                       capture_output=True, text=True, timeout=60)
    out = None
    if os.path.exists(fake + ".out"):
        with open(fake + ".out") as fh:
            out = json.load(fh)
    return r.returncode, r.stdout, r.stderr, out


# ---- forge start @NAME: a session with a profile (4.3 U4) -------------------------------------------------------------------
# The world is test_profiles' (an engine copy, a toy HOME, the project `multi` with the profiles `toy-b` and `list`, `errs`
# whose profiles each fail to resolve, `none` without `profiles`, `frozen-p`), and a PATH that holds only a fake directory
# (claude, python3, git): the fake claude dumps what it was started with, reads the two files the profile gave it (they must
# exist when claude starts), and with FAKE_PEER waits until the other launch's dump exists, so two launches are proved to
# overlap.
FAKE_PROFILE = """#!%s
import json, os, sys, time
argv = sys.argv[1:]
def take(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None
def read(p):
    try:
        with open(p) as fh:
            return fh.read()
    except (OSError, TypeError):
        return None
doc = {"argv": argv, "env": dict(os.environ), "cwd": os.getcwd(), "ppid": os.getppid(),
       "settings": read(take("--settings")), "mcp": read(take("--mcp-config"))}
with open(os.environ["FAKE_OUT"], "w") as fh:
    json.dump(doc, fh)
peer = os.environ.get("FAKE_PEER")
t0 = time.time()
while peer and not os.path.exists(peer):
    if time.time() - t0 > float(os.environ.get("FAKE_PEER_WAIT", "30")):
        sys.exit(99)  # the peer never appeared: not a launch that overlapped, whatever FAKE_EXIT says
    time.sleep(0.05)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
SECRET = "fake-secret-value-123"


def flag(argv, name):
    """The value after `name` in the dumped arguments, or None (no such flag, or no dump): a missing flag is a FAIL line, never a traceback."""
    return argv[argv.index(name) + 1] if argv and name in argv and argv.index(name) + 1 < len(argv) else None


def gap(argv, n_user):
    """How many arguments stand between the value of --mcp-config and the user's n_user arguments: --mcp-config takes any number of
    values (measured, 4.3 U0), so at 0 a prompt at the head of the user's arguments would be swallowed as one."""
    return len(argv) - n_user - (argv.index("--mcp-config") + 2) if argv and "--mcp-config" in argv else None


def sha(p):
    import hashlib
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def profile_cases():
    import test_profiles as tp
    import uuid
    tp.DEFS["toy-sec"] = {"description": "has a secret", "color": "green", "skills": ["toy-a"], "server_kinds": ["vault"],
                          "permissions": {"allow": ["Read"]}, "env": {"TOY_SECRET_ENV": "${TOY_TOKEN}"}}
    tp.PROJECTS["multi"]["profiles"]["offered"]["toy-sec"] = {"servers": {"vault": "toy-sec"}}
    w = tp.World(["multi", "errs", "none", "frozen-p"], skills=tp.SKILLS + ("toy-other",))
    cfg = os.path.join(w.forge, "config")
    tp.write_json(os.path.join(cfg, "mcp-registry.json"), {"servers": {
        "toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}},
        "toy-sec": {"type": "stdio", "command": "toy-sec", "args": [], "env": {"TOY_TOKEN": "${TOY_TOKEN}"}, "deny_tools": ["danger"]}}})
    secrets = os.path.join(w.forge, "credentials", "secrets.json")
    tp.write_json(secrets, {"TOY_TOKEN": SECRET})
    home = w.home
    tp.write_json(os.path.join(home, ".claude", "settings.json"),
                  {"enabledPlugins": {"p-def@m": True, "p-only-default@m": True, "toy-plugin@x": True, "p-other@m": True}})
    tp.write_json(os.path.join(home, ".claude.json"), {"projects": {}, "mcpServers": {}})
    multi = w.pp("multi")
    tp.write_json(os.path.join(multi, ".claude", "settings.local.json"), {"skillOverrides": {"toy-b": "off"}, "enabledPlugins": {"p-other@m": True}})
    os.makedirs(os.path.join(multi, ".claude", "skills", "own-skill"))
    sandbox.git(multi, "add", "-A")
    sandbox.git(multi, "commit", "-q", "--allow-empty", "-m", "c")
    tree = os.path.join(w.root, "linked")
    sandbox.git(multi, "worktree", "add", "-q", tree)
    fakebin = os.path.join(w.root, "fakebin")
    os.makedirs(fakebin)
    with open(os.path.join(fakebin, "claude"), "w") as fh:
        fh.write(FAKE_PROFILE % sys.executable)
    os.chmod(os.path.join(fakebin, "claude"), 0o755)
    os.symlink(sys.executable, os.path.join(fakebin, "python3"))
    import shutil
    os.symlink(shutil.which("git"), os.path.join(fakebin, "git"))
    state = os.path.join(home, ".local", "state", "forge")
    outs = [0]
    dumps = sandbox.mkdtemp("forge-dumps-")  # what the fake claude dumps stays out of the world the tests compare

    def env(extra=None, fake=True):
        outs[0] += 1
        e = sandbox.bare_env(home, w.root, **dict(dict(FAKE_OUT=os.path.join(dumps, "dump-%d.json" % outs[0])), **(extra or {})))
        e["PATH"] = fakebin if fake else os.path.join(w.root, "nobin")
        return e

    def popen(args, cwd, extra=None, fake=True):
        e = env(extra, fake)
        return subprocess.Popen([sys.executable, os.path.join(w.forge, "bin", "forge"), "start"] + args, cwd=cwd, env=e,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), e["FAKE_OUT"]

    def start(args, cwd=multi, extra=None, fake=True):
        """(exit code, stdout, stderr, the fake's dump or None, the launcher's pid)."""
        p, out = popen(args, cwd, extra, fake)
        so, se = p.communicate(timeout=120)
        dump = None
        if os.path.exists(out):
            with open(out) as fh:
                dump = json.load(fh)
        return p.returncode, so, se, dump, p.pid

    def tree_of():
        return w.files("")

    def lists(sub):
        d = os.path.join(state, sub)
        return sorted(os.path.relpath(os.path.join(a, f), d) for a, _, fs in os.walk(d) for f in fs) if os.path.isdir(d) else []

    local, claude_json = os.path.join(multi, ".claude", "settings.local.json"), os.path.join(home, ".claude.json")

    # (1) the arguments of a new session, and (2) the two files that must not change.
    before = {p: sha(p) for p in (local, claude_json)}
    world_before = tree_of()
    user = ["--model", "haiku", "hello world"]
    code, so, se, d, pid = start(["@toy-b"] + user)
    want("1: exit of a profile launch (the fake exits 0)", (code, se), (0, ""))
    argv = d and d["argv"]
    want("1: the arguments carry --settings, --strict-mcp-config, --mcp-config and --session-id",
         [f for f in ("--settings", "--strict-mcp-config", "--mcp-config", "--session-id") if f not in (argv or [])], [])
    want("1: --settings has a value", bool(flag(argv, "--settings")), True)
    want("1: the user's arguments arrive last, untouched", argv and argv[-3:], user)
    want("1: a flag with one value stands between --mcp-config's value and the prompt (else the prompt is swallowed)",
         (gap(argv, len(user)) or 0) > 0, True)
    sid = flag(argv, "--session-id")
    try:
        uuid.UUID(sid)
        valid = True
    except (ValueError, TypeError, AttributeError):
        valid = False
    want("1: the session id is a uuid", valid, True)
    settings = json.loads(d["settings"]) if d and d["settings"] else {}
    want("1: --settings: the profile's skills on, every other global one off, the project's own left out",
         settings.get("skillOverrides"), {"toy-a": "on", "toy-b": "on", "toy-c": "on", "toy-common": "on", "toy-other": "off"})
    want("1: --settings: enabledPlugins names every plugin of the machine (kept on, the rest off)", settings.get("enabledPlugins"),
         {"p-def@m": True, "toy-plugin@x": True, "p-only-default@m": False, "p-other@m": False})
    want("1: --settings: permissions", settings.get("permissions"), {"allow": ["Read"]})
    env_s = settings.get("env") or {}
    want("1: --settings: env (the definition's wins over the common layer's)", (env_s.get("TOY_B"), env_s.get("TOY_ENV")), ("1", "from-def"))
    want("1: the servers file holds the profile's server and nothing else",
         d and json.loads(d["mcp"]) if d and d["mcp"] else None, {"mcpServers": {"toy-echo": {"type": "stdio", "command": "toy-echo", "args": []}}})
    want("1: FORGE_PROFILE and FORGE_PROJECT reach claude", d and (d["env"].get("FORGE_PROFILE"), d["env"].get("FORGE_PROJECT")), ("toy-b", "multi"))
    want("1: claude runs in the directory the command ran in", d and d["cwd"], os.path.realpath(multi))
    under_state = [x for x in (flag(argv, "--settings"), flag(argv, "--mcp-config")) if x]
    want("1: both files are under lib.STATE, regenerated per project and profile",
         [os.path.relpath(x, state) for x in under_state],
         [os.path.join("profile-settings", "multi", "toy-b.json"), os.path.join("profile-settings", "multi", "toy-b.mcp.json")])
    rec_path = os.path.join(state, "profile-sessions", "%s.json" % sid)
    rec = tp.read_json(rec_path) if os.path.exists(rec_path) else None
    want("1: a session record, keyed by the session id", rec and (rec["profile"], rec["project"], rec["launcher_pid"], "parent" in rec),
         ("toy-b", "multi", pid, False))
    want("1: the record's launcher is claude's parent", d and d["ppid"], pid)
    want("1: the record has a time", rec and isinstance(rec.get("at"), (int, float)), True)
    after = {p: sha(p) for p in (local, claude_json)}
    want("2: settings.local.json is the same after the launch", after[local], before[local])
    want("2: ~/.claude.json is the same after the launch", after[claude_json], before[claude_json])
    world_after = tree_of()
    changed = sorted(k for k in set(world_after) | set(world_before) if world_after.get(k) != world_before.get(k))
    want("2: the only files the launch wrote are under lib.STATE/profile-settings and profile-sessions",
         [c for c in changed if not c.startswith(os.path.join("home", ".local", "state", "forge", "profile-"))], [])
    for x in under_state:
        want("2: %s is private (0600), it can hold a secret" % os.path.basename(x), oct(os.stat(x).st_mode & 0o777), "0o600")

    # A resume gets no --session-id and no record; so does a session whose id the user gave.
    n_records = len(lists("profile-sessions"))
    for flags in (["--resume", "abc"], ["--resume=abc"], ["-c"], ["--continue"], ["-r"], ["--session-id", "mine"], ["--session-id=mine"]):
        code, so, se, d, _ = start(["@toy-b"] + flags)
        want("1: %s: no --session-id of forge's own" % flags, (code, d and [a for a in d["argv"] if a.startswith("--session-id")]),
             (0, [f for f in flags if f.startswith("--session-id")]))
        want("1: %s: the user's flags arrive, the profile's too" % flags, d and (d["argv"][-len(flags):] == flags, "--settings" in d["argv"]), (True, True))
    # A prompt at the head of a resume's arguments: no --session-id of ours stands behind --mcp-config's value.
    code, so, se, d, _ = start(["@toy-b", "the prompt", "--resume", "abc"])
    want("1: a prompt before --resume arrives as one, not swallowed by --mcp-config", (d and d["argv"][-3:], (gap(d and d["argv"], 3) or 0) > 0),
         (["the prompt", "--resume", "abc"], True))
    want("1: a resume or a given id writes no record", len(lists("profile-sessions")), n_records)
    code, so, se, d, _ = start(["@toy-b", "--model", "haiku", "--resume", "abc"])
    want("1: a resume among other flags is a resume", d and "--session-id" not in d["argv"], True)
    code, so, se, d, _ = start(["@toy-b"], extra=dict(FAKE_EXIT="7"))
    want("1: claude's exit code is the launcher's", code, 7)

    # The servers and env of a profile with a secret: resolved into 0600 files, never printed, a server's deny_tools denied.
    code, so, se, d, _ = start(["@toy-sec"])
    want("1: toy-sec: exit", (code, se), (0, ""))
    mcp = json.loads(d["mcp"]) if d and d["mcp"] else {}
    st = json.loads(d["settings"]) if d and d["settings"] else {}
    want("1: toy-sec: the server's secret is resolved in the servers file", mcp.get("mcpServers", {}).get("toy-sec", {}).get("env"), {"TOY_TOKEN": SECRET})
    want("1: toy-sec: the env's secret is resolved in --settings", (st.get("env") or {}).get("TOY_SECRET_ENV"), SECRET)
    want("1: toy-sec: the server's deny_tools reach the permissions", (st.get("permissions") or {}).get("deny"), ["mcp__toy-sec__danger"])
    want("1: toy-sec: the secret is in no argument", d and any(SECRET in a for a in d["argv"]), False)
    os.remove(secrets)
    tp.write_json(secrets, {})
    before_missing = tree_of()
    code, so, se, d, _ = start(["@toy-sec"])
    want("1: a secret the store lacks: exit 2, named, claude not run, nothing written", (code, "TOY_TOKEN" in se and "missing" in se, d, tree_of() == before_missing),
         (2, True, None, True))
    tp.write_json(secrets, {"TOY_TOKEN": SECRET})

    # (3) from a linked worktree of the toy project.
    code, so, se, d, pid = start(["@list"], cwd=tree)
    want("3: from a linked worktree: exit", (code, se), (0, ""))
    want("3: it resolves the main checkout's project and runs where it was called",
         d and (d["env"].get("FORGE_PROJECT"), d["cwd"]), ("multi", os.path.realpath(tree)))
    sk = json.loads(d["settings"])["skillOverrides"] if d and d["settings"] else None
    want("3: and the profile's skills (list: toy-a only)", sk, {"toy-a": "on", "toy-common": "on", "toy-b": "off", "toy-c": "off", "toy-other": "off"})

    # (4) the refusals: exit 2, one line, the reason, claude not run.
    refusals = (("a project without profiles", ["@toy-b"], w.pp("none"), "declares no profiles"),
                ("a frozen project", ["@list"], w.pp("frozen-p"), "frozen"),
                ("an unknown name", ["@toy-c"], multi, "toy-b"),
                ("a profile that does not resolve", ["@err-set"], w.pp("errs"), "unknown skill set '@NOPE'"),
                ("a folder that is no project", ["@toy-b"], home, "not inside a project"),
                ("a name that is not a profile", ["toy-b-no-at-and-no-launcher"], multi, "unknown launcher"))
    for label, args, cwd, why in refusals:
        before_r = tree_of()
        code, so, se, d, _ = start(args, cwd=cwd)
        want("4: %s: (exit, claude not run, nothing written)" % label, (code, d, tree_of() == before_r), (2, None, True))
        want("4: %s: one line with the reason %r" % (label, why), (len(se.strip().splitlines()), why in se, se.startswith(("forge start", "! forge start"))),
             (1, True, True))
    code, so, se, d, _ = start(["@toy-"])
    want("4: an unknown name proposes the closest", (code, "did you mean '@toy-b'" in se), (2, True))
    code, so, se, d, _ = start(["@-x"])
    want("4: a name that cannot be one is exit 2", (code, d), (2, None))
    before_r = tree_of()
    code, so, se, d, _ = start(["@toy-b"], fake=False)
    want("4: claude not on PATH is exit 127 naming it, and nothing is written", (code, "claude" in se and "PATH" in se, tree_of() == before_r),
         (127, True, True))
    code, so, se, d, _ = start(["@"])
    want("4: forge start @ lists the project's profiles, as forge list @ does", (code, d, all(x in so for x in ("code", "toy-b", "list", "toy-sec"))),
         (0, None, True))
    code, so, se, d, _ = start(["@"], cwd=w.pp("none"))
    want("4: forge start @ with none says so, as forge list @ does (exit 1)", (code, "no profiles" in so, d), (1, True, None))
    code, so, se, d, _ = start(["@code"])
    want("4: the default's label starts claude with no profile flags, FORGE_PROFILE set",
         (code, d and [f for f in ("--settings", "--mcp-config", "--strict-mcp-config") if f in d["argv"]], d and d["env"].get("FORGE_PROFILE")),
         (0, [], "code"))

    # (5) two launches at once, different profiles: different files and records, and they overlap. The fake waits for the other's
    # dump and exits 99 when it never comes, so the "both exit 0" below fails on launches that ran one after the other. The control
    # (a peer file that never appears, a 1 s wait) must exit 99; with the fake's timeout exit set to 0 instead it failed with
    # "FAIL 5: control: a peer that never appears makes the fake exit 99: 0, want 99", and with 99 it passes.
    code, so, se, d, _ = start(["@toy-b"], extra=dict(FAKE_PEER=os.path.join(dumps, "never-appears.json"), FAKE_PEER_WAIT="1"))
    want("5: control: a peer that never appears makes the fake exit 99", code, 99)
    oa, ob = os.path.join(dumps, "peer-a.json"), os.path.join(dumps, "peer-b.json")
    pa, _ = popen(["@toy-b"], multi, dict(FAKE_OUT=oa, FAKE_PEER=ob))  # each fake waits for the other's dump: they overlap
    pb, _ = popen(["@list"], multi, dict(FAKE_OUT=ob, FAKE_PEER=oa))
    pa.communicate(timeout=60)
    pb.communicate(timeout=60)
    da, db = (json.load(open(o)) if os.path.exists(o) else None for o in (oa, ob))
    want("5: both launches ran", (pa.returncode, pb.returncode, da is not None, db is not None), (0, 0, True, True))
    if da and db:
        fa, fb = flag(da["argv"], "--settings"), flag(db["argv"], "--settings")
        ma, mb = flag(da["argv"], "--mcp-config"), flag(db["argv"], "--mcp-config")
        want("5: different settings files, servers files and session ids",
             (fa != fb, ma != mb, flag(da["argv"], "--session-id") != flag(db["argv"], "--session-id")), (True, True, True))
        want("5: each file holds its own profile's lists", tuple((json.loads(x["settings"] or "{}").get("skillOverrides") or {}).get("toy-b")
                                                                 for x in (da, db)), ("on", "off"))
        recs = {os.path.basename(x): tp.read_json(os.path.join(state, "profile-sessions", x)) for x in lists("profile-sessions")}
        profs = sorted(r["profile"] for r in recs.values() if r["launcher_pid"] in (pa.pid, pb.pid))
        want("5: two records, one per profile", profs, ["list", "toy-b"])

    # The profile's own flags are not the user's to repeat: with two --settings claude keeps the last, so the user's would silently
    # replace the profile (skills, plugins, env, denied tools) while FORGE_PROFILE and the record still say it is active. Red on
    # 2f85ddd: "FAIL 4: ['--settings', 'X']: refused, claude not run, nothing written: (0, {'argv': [...'--settings', '.../toy-b.json',
    # ..., '--settings', 'X'], ...}, False), want (2, None, True)" (the fake claude received both flags and the launch exited 0).
    for given in (["--settings", "X"], ["--settings=X"], ["--mcp-config", "X"], ["--mcp-config=X"], ["--strict-mcp-config"],
                  ["--", "--settings", "X"], ["hello", "--model", "haiku", "--settings=X"]):
        before_s = tree_of()
        code, so, se, d, _ = start(["@toy-b"] + given)
        flag_name = next(a.split("=")[0] for a in given if a.split("=")[0] in ("--settings", "--mcp-config", "--strict-mcp-config"))
        want("4: %s: refused, claude not run, nothing written" % given, (code, d, tree_of() == before_s), (2, None, True))
        want("4: %s: one line naming %s and saying the profile sets it" % (given, flag_name),
             (se.strip() == "! forge start: %s is set by the profile: a profile start refuses it in ARGS" % flag_name), True)
    code, so, se, d, _ = start(["@toy-b", "--dry-run", "--settings", "X"])
    want("4: the refusal comes before a dry-run too", (code, "is set by the profile" in se), (2, True))
    code, so, se, d, _ = start(["@code", "--settings", "X"])
    want("4: the default label sets none of the three, so they are the user's", (code, d and d["argv"][-2:]), (0, ["--settings", "X"]))

    # A state folder that cannot be written is one line and claude is not started, never a traceback.
    sessions = os.path.join(state, "profile-sessions")
    shutil.rmtree(sessions)
    open(sessions, "w").close()  # a file where the folder of the records goes
    code, so, se, d, _ = start(["@toy-b"])
    want("4: state that cannot be written: exit 2, one line, no traceback, claude not run",
         (code, len(se.strip().splitlines()), "cannot write" in se and "Traceback" not in se, d), (2, 1, True, None))
    os.remove(sessions)

    # (6) --dry-run: the arguments, the environment and the files; nothing written.
    before_d = tree_of()
    for args in (["@toy-sec", "--dry-run", "--model", "haiku"], ["--dry-run", "@toy-sec", "--model", "haiku"]):
        code, so, se, d, _ = start(args)
        want("6: %s: exit 0, claude not run, nothing written" % args, (code, se, d, tree_of() == before_d), (0, "", None, True))
        for label, parts in (("the arguments", ("--settings", "--strict-mcp-config", "--mcp-config", "--session-id", "--model haiku")),
                             ("the environment it would set", ("FORGE_PROFILE=toy-sec", "FORGE_PROJECT=multi")),
                             ("the files it would write", ("profile-settings/multi/toy-sec.json", "profile-settings/multi/toy-sec.mcp.json", "profile-sessions/"))):
            want("6: %s: %s" % (args, label), [x for x in parts if x not in so], [])
        want("6: %s: no secret printed" % args, SECRET in so + se, False)
    code, so, se, d, _ = start(["@toy-b", "--dry-run", "--model", "haiku"], fake=False)
    want("6: claude not on PATH, dry-run: exit 127", code, 127)
    code, so, se, d, _ = start(["--dry-run", "toy-launcher"])
    want("6: --dry-run is for @NAME: with a launcher name it is exit 2", (code, d, "--dry-run" in se), (2, None, True))
    code, so, se, d, _ = start(["--dry-run"])
    want("6: --dry-run alone is exit 2", (code, d), (2, None))


def main():
    try:
        return run_all()
    finally:
        sandbox.cleanup()  # also when a case raised: a test that leaves a folder in /tmp is a bug in that test (ORDERS 14)


def run_all():
    profile_cases()
    with tempfile.TemporaryDirectory(prefix="forge-launch-") as tmp:
        n = [0]

        def run(*a, **k):
            n[0] += 1
            d = os.path.join(tmp, str(n[0]))
            os.makedirs(d)
            return launch(d, *a, **k)
        code, _, err, out = run(LAUNCHERS, ["start", "orq"])
        want("exit of a launch (the fake exits 0)", (code, err), (0, ""))
        want("env reaches claude: CACHE_TAX_AUTOWARM", out and out["orq"], "on")
        want("the caller's variables stay", out and out["kept"], "mine")
        want("a variable of another launcher is not added", out and out["other"], None)
        code, _, _, out = run(LAUNCHERS, ["start", "plain"])
        want("the other launcher: its variable", out and out["other"], "x")
        want("the other launcher: orq's variable is absent", out and out["orq"], None)
        argv = ["--model", "opus", "-c", "--", "-p", "two words", ""]
        code, _, _, out = run(LAUNCHERS, ["start", "orq"] + argv)
        want("args after NAME arrive untouched", out and out["argv"], argv)
        code, _, _, out = run(LAUNCHERS, ["start", "orq", "--help"])
        want("--help after NAME goes to claude", out and out["argv"], ["--help"])
        code, so, _, out = run(LAUNCHERS, ["start"])
        want("no name lists (exit, claude not run)", (code, out), (0, None))
        want("no name lists: names and env keys", ("orq" in so and "CACHE_TAX_AUTOWARM" in so and "plain" in so
                                                   and "OTHER_VAR" in so), True)
        want("no name lists: the key of a third launcher, never a value", ("SECRET_VAR" in so, "hunter2" in so), (True, False))
        for label, doc in (("none configured", None), ("empty", {})):
            code, so, _, out = run(doc, ["start"])
            want("no name, %s: (exit, says so, claude not run)" % label, (code, "no launchers" in so, out), (0, True, None))
        code, _, err, out = run(LAUNCHERS, ["start", "nope"])
        want("unknown name: (exit, claude not run)", (code, out), (2, None))
        want("unknown name: names the known ones", ("orq" in err and "plain" in err and "nope" in err), True)
        code, _, err, out = run(None, ["start", "orq"])
        want("unknown name with none configured: exit", code, 2)
        bad = (("launchers not an object", ["orq"], "launchers"),
               ("launcher not an object", {"orq": "on"}, "orq"),
               ("env not an object", {"orq": {"env": ["A"]}}, "orq"),
               ("a value that is not a string", {"orq": {"env": {"CACHE_TAX_AUTOWARM": True}}}, "CACHE_TAX_AUTOWARM"),
               ("a key with =", {"orq": {"env": {"A=B": "1"}}}, "A=B"),
               ("a key forge does not know", {"orq": {"envs": {}}}, "envs"))
        for label, launchers, key in bad:
            for args in (["start", "orq"], ["start"]):
                code, _, err, out = run(launchers, args)
                want("malformed (%s), %s: (exit, claude not run, names %r)" % (label, args, key),
                     (code, out, key in err), (2, None, True))
        code, _, err, out = run(LAUNCHERS, ["start", "orq"], with_claude=False)
        want("claude not on PATH: (exit, says so)", (code, "claude" in err and "PATH" in err), (127, True))
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print("ok: launch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
