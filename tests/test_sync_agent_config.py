#!/usr/bin/env python3
"""sync_agent_config.py rewrites files it does not own alone -- ~/.claude.json above all, which
every Claude Code session writes too. This runs forge/sync.py's agent_config() in-process against a
toy HOME and a toy config/ (the real machine is never touched: HOME is swapped before import, and
everything that reaches systemd, VS Code or the Hindsight runtime is stubbed) and checks the ways a
run used to destroy what was already there.

Each case seeds the state the old code got wrong, so every assertion has been seen to fail."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("agent-config-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
# Codex's own way to move ~/.codex; memory_doctor.py honoured it and the generator did not.
CODEX_HOME = os.path.join(HOME, "codex-home")
os.environ["CODEX_HOME"] = CODEX_HOME
# FORGE_WRITE_LOG names a caller's log (forge/cli.py sets it for the steps a session start runs):
# this run's toy writes are not theirs to log.
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG"):
    os.environ.pop(var, None)
# The generator asks git what it ignores: no global excludes file may answer for the toy repos.
os.environ.pop("XDG_CONFIG_HOME", None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from forge import lib  # noqa: E402
# The settings every case runs on are the fixture's, never this machine's config/forge.json: a copy_engine
# copy has none (red there before, M1: "! config/forge.json missing -- run bin/forge init" at the import
# of forge.hooks). Every integration on but jev, whose setup.py is a private skill: where this checkout has
# that skill, jev is on too, as it is on the machine that has it.
FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "config")
HAVE_JEV = os.path.exists(os.path.join(sandbox.FORGE, "skills", "jev", "scripts", "setup.py"))
lib.SETTINGS = os.path.join(FIXTURES, "forge.json")
if HAVE_JEV:
    with open(lib.SETTINGS, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["integrations"]["jev"] = True
    lib.SETTINGS = os.path.join(TOY, "forge-jev.json")
    with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
from forge import hooks, mcp, memory, skills, sync  # noqa: E402

assert hooks.HOME == HOME and hooks.USER_SETTINGS.startswith(HOME + os.sep), "the import saw the real HOME"
assert lib.HOME == HOME and lib.CODEX_HOME == CODEX_HOME, "forge/lib.py saw the real HOME"
# agent_config() builds its Ctx with lib.context(argv); every run here gets run_ctx instead,
# which each case sets (apply included), as sac.ctx was set before the S7 split.
run_ctx = lib.context([])._replace(apply=True)
lib.context = lambda argv: run_ctx
memory.LITE_ROOT = os.path.join(TOY, "lite")
real_write_hindsight_config = memory.write_hindsight_config  # case 5 calls it on a toy ROOT
real_check_hindsight_runtime = memory.check_hindsight_runtime  # and case 17 this one
# Everything that reaches systemd, VS Code or the Hindsight runtime is stubbed, and each stub says
# it ran: a run that went around one would reach the real thing and nothing here would notice.
ran = set()


def stub(module, name, result):
    """Replace module.name. A name the module does not have is refused: the function moved, and a
    stub set beside it would leave the real one to run (systemd, the real proxy)."""
    if not callable(getattr(module, name, None)):
        sys.exit("STUB: %s has no %s -- nothing run" % (module.__name__, name))

    def f(*args):
        ran.add(name)
        return result
    setattr(module, name, f)


stub(hooks, "write_jev_proxy", ("   jev proxy (stub)", False))
stub(hooks, "write_jev_status_extension", "   jev extension (stub)")
stub(memory, "write_hindsight_config", "   hindsight config (stub)")
stub(memory, "check_hindsight_runtime", None)
STUBS = {"write_jev_proxy", "write_jev_status_extension", "write_hindsight_config", "check_hindsight_runtime"}

CJ = os.path.join(HOME, ".claude.json")
failures = []
n_cases = 0


def check(ok, msg):
    global n_cases
    n_cases += 1
    if not ok:
        failures.append(msg)


def fence(pdir):
    """End the whole test before agent_config() runs unless every path it could write is inside TOY.

    run_ctx's apply=True skips lib.may_write, the rule that keeps a copy of forge off the real
    projects, while lib.PROFILES names the real checkout's profiles. The generator lists its
    profiles from lib.PROFILES, so left at the real directory it would write the 19 real projects;
    sync.CFG is still where it reads the registry, the secrets and the relocations. So both are the
    toy ones, and no toy profile names a directory outside TOY."""
    if lib.PROFILES != pdir or os.path.join(sync.CFG, "profiles") != pdir:
        sys.exit("FENCE: profiles are read from %s and %s, not the toy %s -- nothing run"
                 % (lib.PROFILES, os.path.join(sync.CFG, "profiles"), pdir))
    for f in sorted(os.listdir(pdir)):
        try:
            with open(os.path.join(pdir, f), encoding="utf-8") as fh:
                prof = json.load(fh)
        except ValueError:
            continue  # the generator reads it as {}: no directory to write
        pp = prof.get("project_path") if isinstance(prof, dict) else None
        # A path that is not a string names no directory: the generator skips that profile.
        if isinstance(pp, str) and pp and not os.path.realpath(pp).startswith(TOY + os.sep):
            sys.exit("FENCE: %s names %s, outside the toy world %s -- nothing run" % (f, pp, TOY))


def case(name, profiles, relocations=(), only=None, globals_=False, secrets_link=True, registry=None):
    """A fresh toy config/ and project dirs; returns (exit code, stdout, {name: project dir}).
    A profile given as a string is written as that text, unparsed, and so is `relocations` given
    as a string. `registry` is the registry's text, written unparsed; None is an empty servers
    object, False no registry file at all."""
    global run_ctx
    base = os.path.join(TOY, name)
    cfg, pdir = os.path.join(base, "config"), os.path.join(base, "config", "profiles")
    os.makedirs(pdir)
    if registry is not False:
        seed(os.path.join(cfg, "mcp-registry.json"), '{"servers": {}}' if registry is None else registry)
    with open(os.path.join(base, "secrets.json"), "w") as f:
        f.write("{}")
    # A symlink, as on the machine; "copy" makes the stale plain file of case 15b.
    if secrets_link == "copy":  # a stale copy: credentials/ has a key the copy lacks
        seed(os.path.join(base, "credentials", "secrets.json"), '{"ADDED_SINCE": "fake"}')
        seed(os.path.join(cfg, "secrets.json"), "{}")
    elif secrets_link:
        os.symlink(os.path.join(base, "secrets.json"), os.path.join(cfg, "secrets.json"))
    if isinstance(relocations, str):  # the file's text, written unparsed
        seed(os.path.join(cfg, "project-relocations.json"), relocations)
    else:
        with open(os.path.join(cfg, "project-relocations.json"), "w") as f:
            json.dump({"relocations": list(relocations)}, f)
    dirs = {}
    for pname, prof in profiles.items():
        if isinstance(prof, str):
            seed(os.path.join(pdir, pname + ".claude.json"), prof)
            continue
        prof = dict(prof)
        prof.setdefault("project", pname)
        prof.setdefault("servers", [])
        if "project_path" not in prof:
            prof["project_path"] = os.path.join(base, "projects", pname)
        if prof["project_path"] is None:
            del prof["project_path"]  # a profile that names no directory
        else:
            dirs[pname] = prof["project_path"]
        with open(os.path.join(pdir, pname + ".claude.json"), "w") as f:
            json.dump(prof, f)
    sync.CFG, run_ctx = cfg, lib.Ctx(run_ctx.apply, only, globals_)
    lib.PROFILES = pdir
    fence(pdir)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    ran.clear()
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out):
        try:
            code = sync.agent_config([])
        except SystemExit as e:
            code = e.code
        except Exception as e:  # a crash is a result too, and a readable one
            code = "raised %s: %s" % (type(e).__name__, e)
    exit_rule(name, code, out.getvalue())
    if globals_:
        check(ran == STUBS, "%s: stub(s) %s never ran -- the run went around them"
              % (name, ", ".join(sorted(STUBS - ran))))
    return code, out.getvalue(), dirs


BANG = re.compile(r"(?m)^\s*!")


def exit_rule(name, code, out):
    """forge/sync.py agent_config's one exit rule, on every run here: a line whose first non-space
    character is '!' means exit 1, and no other line does. A crash (code "raised ...") breaks it
    too. Red on 0ad2214, before the rule, for 28 runs, each "exit 0 with a '!' line":
    "env-null-first: exit 0 with a '!' line, first '   ! env is not an object, left alone' -- the
    exit rule" (and env-null-again, env-list-first, env-list-again); "dupmerge: ... first '   !
    removing duplicate project key: <toy>/dupmerge/projects/a/'"; reloc-frozen and
    reloc-frozen-scoped ("! relocation ... skipped: a frozen project's key is never touched");
    gi-link-outside, gi-link-inside, codex-link-config-toml, codex-link-codex ("! codex mcp -> ...
    NOT written"); mirror-gi-link and agents-file-0/1/2 (the codex or mirror NOT written/linked
    line); no-secrets-link ("!! config/secrets.json is missing, so no secret resolves.");
    secrets-copy ("!! config/secrets.json is a COPY ..."); reloc-shape-0..4, reloc-entry-0..4 and
    reloc-broken ("  ! config/project-relocations.json holds a list, not an object -- no
    relocation applied", "  ! could not read <toy>/reloc-broken/config/project-relocations.json:
    ...")."""
    bang = BANG.search(out)
    if bool(bang) != (code != 0):
        first = out[bang.start():].lstrip("\n").splitlines()[0] if bang else None
        check(False, "%s: exit %r with%s a '!' line%s -- the exit rule"
              % (name, code, "" if bang else "out", ", first %r" % first if bang else ""))
    else:
        check(True, "")


def seed(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def reset_home():
    shutil.rmtree(HOME)
    os.makedirs(HOME)


def repo(d):
    """d as a git repository, so the .gitignore checks run."""
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)


def mode_of(p):
    try:
        return os.stat(p).st_mode & 0o777
    except OSError:
        return None


# 1. A file the generator rewrites whole is read strictly: missing is {}, anything else
# unreadable is left byte for byte and the run exits 1. Before the fix load() turned a
# truncated ~/.claude.json into {} and --apply wrote back only forge's keys -- oauthAccount,
# trust and every other project's history gone.
# Valid JSON whose top level is not an object is unreadable too: before round 2 a null
# ~/.claude.json crashed the run with an AttributeError, and a null or list hooks.json was
# silently replaced ("reset (was not an object)").
CORRUPT = '{"oauthAccount": {"x": 1}, "projects": {"other": "data"},'
for target in (CJ, os.path.join(HOME, ".claude", "settings.json"), os.path.join(CODEX_HOME, "hooks.json")):
    for i, text in enumerate((CORRUPT, "null", "[1]")):
        reset_home()
        seed(target, text)
        code, out, _ = case("corrupt-%s-%d" % (os.path.basename(target), i), {"a": {}}, globals_=True)
        short = target.replace(HOME, "~")
        what = "%s holding %s" % (short, "truncated JSON" if text == CORRUPT else text)
        check(read(target) == text, "corrupt %s was rewritten: %r" % (what, read(target)[:80]))
        check(code == 1, "corrupt %s: exit %r, want 1" % (what, code))
        check(any(l.lstrip().startswith("! %s unreadable" % short) for l in out.splitlines()),
              "corrupt %s: no '! %s unreadable' line in the output" % (what, short))
        # The closing line points at the '!' lines, an unreadable file among the causes: it used
        # to blame only secrets or a profile.
        check(any(l.startswith("ABORTED") and "'!' line" in l and "unreadable file" in l for l in out.splitlines()),
              "corrupt %s: the ABORTED line does not point at the '!' lines: %r"
              % (what, [l for l in out.splitlines() if l.startswith("ABORTED")]))

# settings.local.json merges the permissions a session approved, so it carries the same risk.
reset_home()
d = os.path.join(TOY, "corrupt-local", "projects", "a")
seed(os.path.join(d, ".claude", "settings.local.json"), CORRUPT)
code, out, _ = case("corrupt-local", {"a": {"permissions": {"allow": ["Bash(ls:*)"]}}})
check(read(os.path.join(d, ".claude", "settings.local.json")) == CORRUPT, "corrupt settings.local.json was rewritten")
check(code == 1, "corrupt settings.local.json: exit %r, want 1" % code)

# Positive control: missing files are still created, so the strict read did not just stop writing.
reset_home()
code, out, dirs = case("missing", {"a": {}}, globals_=True)
check(code == 0, "clean toy run: exit %r, want 0\n%s" % (code, out))
check(os.path.exists(CJ) and dirs["a"] in json.loads(read(CJ)).get("projects", {}),
      "clean toy run did not write the project key into a missing ~/.claude.json")
# Codex gets no hook from forge: no hooks.json is created, in $CODEX_HOME or in ~/.codex. Red before:
# "clean toy run created $CODEX_HOME/hooks.json".
check(os.path.exists(hooks.USER_SETTINGS) and not os.path.exists(os.path.join(CODEX_HOME, "hooks.json"))
      and not os.path.exists(os.path.join(HOME, ".codex")),
      "clean toy run did not create settings.json, or created $CODEX_HOME/hooks.json or ~/.codex: "
      "the generator's hooks.json is %s" % hooks.CODEX_HOOKS.replace(HOME, "~"))

# 3. A key relocation never touches a frozen project's key (unify-plan rule 1: forge writes El
# Portal not one byte), and a scoped run relocates only its own projects' keys.
reset_home()
portal = os.path.join(TOY, "reloc-frozen", "projects", "portal")
seeded = {"projects": {portal: {"hasTrustDialogAccepted": True},
                       "/old/into-portal": {"allowedTools": ["x"]}}}
seed(CJ, json.dumps(seeded))
code, out, _ = case("reloc-frozen", {"portal": {"frozen": True}, "a": {}},
                    relocations=[{"from": portal, "to": "/elsewhere"}, {"from": "/old/into-portal", "to": portal}])
got = json.loads(read(CJ))["projects"]
check(got.get(portal) == seeded["projects"][portal] and "/old/into-portal" in got and "/elsewhere" not in got,
      "a relocation touched the frozen project's key: %r" % {k: got.get(k) for k in (portal, "/old/into-portal", "/elsewhere")})
check(sum(1 for l in out.splitlines() if l.lstrip().startswith("! relocation")) == 2,
      "no '! relocation ... skipped' warning for each frozen relocation:\n" + out)

# Scoped to another project, a relocation onto the frozen key is still refused.
reset_home()
portal = os.path.join(TOY, "reloc-frozen-scoped", "projects", "portal")
a = os.path.join(TOY, "reloc-frozen-scoped", "projects", "a")
seed(CJ, json.dumps({"projects": {a: {"allowedTools": ["x"]}}}))
code, out, _ = case("reloc-frozen-scoped", {"portal": {"frozen": True}, "a": {}},
                    relocations=[{"from": a, "to": portal}], only={"a"})
check(portal not in json.loads(read(CJ))["projects"], "a run scoped to 'a' relocated a's key onto the frozen one")

# A frozen profile gets nothing from forge, so it need not even name a directory.
reset_home()
code, out, _ = case("frozen-no-path", {"portal": {"frozen": True, "project_path": None}, "a": {}},
                    relocations=[{"from": "/old/a", "to": "/new/a"}])
check(code == 0, "a frozen profile without project_path: exit %r\n%s" % (code, out[-300:]))

for only, moved in (({"a"}, False), ({"b"}, True), (None, True)):
    reset_home()
    name = "reloc-only-%s" % (",".join(sorted(only)) if only else "all")
    b = os.path.join(TOY, name, "projects", "b")
    seed(CJ, json.dumps({"projects": {"/old/b": {"allowedTools": ["y"]}}}))
    code, out, _ = case(name, {"a": {}, "b": {}}, relocations=[{"from": "/old/b", "to": b}], only=only)
    got = json.loads(read(CJ))["projects"]
    check(("/old/b" not in got and got.get(b, {}).get("allowedTools") == ["y"]) == moved,
          "run scoped to %r: relocation of b's key %s" % (only, "not applied" if moved else "applied anyway"))

# 4. One key per project, in the form Claude Code writes: a trailing slash in a profile does not
# become the key (that turned the real key into the "duplicate" and deleted it every session),
# folding a duplicate keeps its whole entry, and on Linux a key differing only in case is
# another directory, not a duplicate.
reset_home()
base = os.path.join(TOY, "dupkey", "projects")
a, A = os.path.join(base, "a"), os.path.join(base, "A")
entry = {"allowedTools": ["Bash(ls:*)"], "hasTrustDialogAccepted": True, "disabledMcpServers": ["x"]}
seed(CJ, json.dumps({"projects": {a: dict(entry), A: {"allowedTools": ["other dir"]}}}))
code, out, _ = case("dupkey", {"a": {"project_path": a + "/"}})
got = json.loads(read(CJ))["projects"]
check(a + "/" not in got, "a trailing slash in project_path became the key %r" % (a + "/"))
check(all(got.get(a, {}).get(k) == v for k, v in entry.items()),
      "the real key lost its entry: %r" % got.get(a))
check(got.get(A) == {"allowedTools": ["other dir"]}, "a case-distinct key was folded in: %r" % sorted(got))

reset_home()
base = os.path.join(TOY, "dupmerge", "projects")
a = os.path.join(base, "a")
seed(CJ, json.dumps({"projects": {a: {"allowedTools": ["canonical wins"]}, a + "/": dict(entry)}}))
code, out, _ = case("dupmerge", {"a": {}})
got = json.loads(read(CJ))["projects"]
want = dict(entry, allowedTools=["canonical wins"])
check(a + "/" not in got and all(got.get(a, {}).get(k) == v for k, v in want.items()),
      "folding the duplicate key lost part of its entry: %r" % got)

# The same fold when a relocation lands on a key that already exists.
reset_home()
b = os.path.join(TOY, "relocmerge", "projects", "b")
seed(CJ, json.dumps({"projects": {"/old/b": dict(entry), b: {"allowedTools": ["canonical wins"]}}}))
code, out, _ = case("relocmerge", {"b": {}}, relocations=[{"from": "/old/b", "to": b}])
got = json.loads(read(CJ))["projects"]
check("/old/b" not in got and all(got.get(b, {}).get(k) == v for k, v in want.items()),
      "a relocation onto an existing key lost part of the old entry: %r" % got.get(b))

# A relocation's ends are keys too, compared and written in project_key() form: a trailing
# slash or a `.` in config/project-relocations.json used to miss the key, or move it onto a
# non-canonical one, or move it onto itself.
for label, cj, item, want in (
        ("a from with a trailing slash", {"/old/b": {"k": 1}}, {"from": "/old/b/", "to": "/new/./b"}, {"/new/b": {"k": 1}}),
        ("a to equal to its from", {"/p/x": {"k": 1}}, {"from": "/p/x", "to": "/p/x/"}, {"/p/x": {"k": 1}})):
    cj = {"projects": cj}
    moved = mcp.migrate_project_keys(cj, [item])
    check(cj["projects"] == want, "relocation %s %r: keys %r, want %r (moved %r)" % (label, item, cj["projects"], want, moved))

# 5. A file written 0600 is never anything else, not for an instant: every chmod and replace the
# write does is recorded with the mode its target has at that moment. Before the fix the temp
# file was created at the umask default and chmodded after it held the text, the Hindsight
# config (a bearer in clear) was swapped in at 644 and chmodded after, and a .bak was 644 until
# its chmod -- or for good, when it predated the file's mode.
os.umask(0o022)
seen = []
real_chmod, real_replace = os.chmod, os.replace


os.chmod = lambda p, m, *a, **k: (seen.append((p, mode_of(p))), real_chmod(p, m, *a, **k))[1]
os.replace = lambda s, d, *a, **k: (seen.append((s, mode_of(s))), real_replace(s, d, *a, **k))[1]


def loose(where):
    bad = ["%s at %o" % (p.replace(TOY, ""), m) for p, m in seen if m is not None and m & 0o077]
    check(not bad, "%s: a secret file was readable by others mid-write: %s" % (where, ", ".join(bad)))
    del seen[:]


reset_home()
sec = os.path.join(HOME, "secret.json")
lib.write_text(sec, "one", mode=0o600, backup=True)
loose("new file")
seed(sec, "one")
real_chmod(sec, 0o644)  # an existing file at the umask default: its first .bak is made now
lib.write_text(sec, "two", mode=0o600, backup=True)
loose("existing file and its first .bak")
check(mode_of(sec) == 0o600 and mode_of(sec + ".bak") == 0o600,
      "after the write: file %o, .bak %o, want 600 both" % (mode_of(sec), mode_of(sec + ".bak")))
real_chmod(sec + ".bak", 0o644)  # a .bak left from before the file carried a mode
lib.write_text(sec, "three", mode=0o600, backup=True)
check(mode_of(sec + ".bak") == 0o600, "a pre-existing 644 .bak of a 600 file stayed %o" % mode_of(sec + ".bak"))
del seen[:]

toy_root = os.path.join(TOY, "root")
seed(os.path.join(toy_root, "config", "hindsight-coding-agents.json"), json.dumps({"apiToken": "${TOK}", "bank": "b"}))
target = os.path.join(HOME, ".hindsight", "coding-agent.json")
real_root, memory.ROOT = memory.ROOT, toy_root
for label in ("created", "rewritten"):
    errs = []
    line = real_write_hindsight_config(run_ctx, {"TOK": "fake-%s" % label}, errs)
    check(not errs and mode_of(target) == 0o600, "hindsight config %s: %r, mode %s, errors %r"
          % (label, line, mode_of(target) and "%o" % mode_of(target), errs))
    loose("hindsight config " + label)
# A current config beside a 644 .bak (the machine's state on the bearer in both): the
# unchanged-content return came before any .bak check, so the .bak stayed 644 for good.
real_chmod(target + ".bak", 0o644)
run_ctx = run_ctx._replace(apply=False)
dry = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
run_ctx = run_ctx._replace(apply=True)
line = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
check("would chmod 600 ~/.hindsight/coding-agent.json.bak (content current)" in dry
      and "chmod 600 coding-agent.json.bak" in line and mode_of(target + ".bak") == 0o600,
      "a current hindsight config and its 644 .bak: .bak %o, dry-run %r, apply %r" % (mode_of(target + ".bak"), dry, line))
real_chmod(target, 0o644)  # the file alone: today's texts, unchanged
run_ctx = run_ctx._replace(apply=False)
dry = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
run_ctx = run_ctx._replace(apply=True)
line = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
check(dry == "   would chmod 600 ~/.hindsight/coding-agent.json (content current)"
      and line == "   config -> ~/.hindsight/coding-agent.json (content current, mode corrected to 600)"
      and mode_of(target) == 0o600, "a current 644 hindsight config: mode %o, dry-run %r, apply %r" % (mode_of(target), dry, line))
del seen[:]  # both were loose before these runs; they are chmodded, not written
# A linked config: ~/.hindsight/coding-agent.json points at a current 600 file elsewhere, and the
# once-ever .bak lib.write_json keeps beside that resolved file is 644. memory looked for the .bak
# beside the link, where write_json never puts one, so the .bak holding the bearer was never seen.
# Red on 1e34c0f: "a linked hindsight config and a 644 .bak beside its target: .bak 644, link kept
# True, dry-run '   config -> ~/.hindsight/coding-agent.json (already current)', apply '   config
# -> ~/.hindsight/coding-agent.json (already current)'".
elsewhere = os.path.join(TOY, "hindsight-real", "coding-agent.json")
os.makedirs(os.path.dirname(elsewhere))
os.rename(target, elsewhere)
os.rename(target + ".bak", elsewhere + ".bak")
os.symlink(elsewhere, target)
real_chmod(elsewhere + ".bak", 0o644)
before = read(elsewhere)
run_ctx = run_ctx._replace(apply=False)
dry = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
dry_bak = mode_of(elsewhere + ".bak")
run_ctx = run_ctx._replace(apply=True)
line = real_write_hindsight_config(run_ctx, {"TOK": "fake-rewritten"}, [])
check(dry == "   would chmod 600 %s.bak (content current)" % elsewhere and dry_bak == 0o644
      and line == "   config -> ~/.hindsight/coding-agent.json (content current, chmod 600 coding-agent.json.bak)"
      and mode_of(elsewhere + ".bak") == 0o600 and mode_of(elsewhere) == 0o600
      and os.path.islink(target) and read(elsewhere) == before,
      "a linked hindsight config and a 644 .bak beside its target: .bak %o, link kept %s, dry-run %r, apply %r"
      % (mode_of(elsewhere + ".bak"), os.path.islink(target), dry, line))
del seen[:]
memory.ROOT = real_root
os.chmod, os.replace = real_chmod, real_replace

# 6. <project>/.codex/config.toml carries resolved secrets: it is written 0600, and a copy
# already on disk -- or its once-ever .bak -- at the umask default is brought to 0600 even when
# its content is current. Round 2 found them 644 on the machine, and every project's .bak too.
os.umask(0o022)
reset_home()
d = os.path.join(TOY, "codex-mode", "projects", "a")
repo(d)
toml = os.path.join(d, ".codex", "config.toml")
code, out, _ = case("codex-mode", {"a": {}})
check(code == 0 and mode_of(toml) == 0o600, "a new .codex/config.toml: exit %r, mode %s, want 600"
      % (code, mode_of(toml) and "%o" % mode_of(toml)))
body = read(toml)
os.chmod(toml, 0o644)
seed(toml + ".bak", "an older copy, same secrets")
os.chmod(toml + ".bak", 0o644)
run_ctx = run_ctx._replace(apply=False)
code, out, _ = case("codex-mode-dry", {"a": {"project_path": d}})
check(code == 0 and "would chmod 600" in out and mode_of(toml) == 0o644,
      "dry-run over a current 644 config.toml: exit %r, mode %o, no 'would chmod 600' in %r"
      % (code, mode_of(toml), [l for l in out.splitlines() if "codex mcp" in l]))
run_ctx = run_ctx._replace(apply=True)
code, out, _ = case("codex-mode-apply", {"a": {"project_path": d}})
check(code == 0 and read(toml) == body and (mode_of(toml), mode_of(toml + ".bak")) == (0o600, 0o600)
      and "chmod 600" in out, "--apply over a current 644 config.toml and 644 .bak: modes %s, output %r"
      % (["%o" % (mode_of(p) or 0) for p in (toml, toml + ".bak")], [l for l in out.splitlines() if "codex mcp" in l]))
os.chmod(toml + ".bak", 0o644)  # the machine's state: a 600 file hand-fixed, its .bak left 644
code, out, _ = case("codex-mode-bak", {"a": {"project_path": d}})
check(code == 0 and mode_of(toml + ".bak") == 0o600 and "chmod 600 config.toml.bak" in out,
      "--apply over a current 600 config.toml and its 644 .bak: .bak %o, output %r"
      % (mode_of(toml + ".bak"), [l for l in out.splitlines() if "codex mcp" in l]))

# 6b. ~/.claude.json's once-ever .bak holds the same resolved secrets, and is brought to 0600 on a
# run whose content is current: ClaudeJson.commit() returned "already current" before any .bak
# check, so a 644 .bak beside a 600 file stayed 644 for good (round 5). A .bak that is a link is
# never chmodded: os.chmod follows it to someone else's file. Red on 49e6f9d:
# "a current 600 ~/.claude.json beside a 644 .bak: .bak 644, dry-run [], apply [], current dry True, apply True".
# The link case passed there (nothing touched a .bak); with mcp.loose_files' islink() test removed:
# "a ~/.claude.json.bak that is a link: exit 0, link kept True, its target 600, lines ['chmod 600
# ~/.claude.json.bak (it carries resolved secrets)']"
reset_home()
d = os.path.join(TOY, "cjbak", "projects", "a")
code, out, _ = case("cjbak", {"a": {"project_path": d}})
check(code == 0 and mode_of(CJ) == 0o600, "a new ~/.claude.json: exit %r, mode %s" % (code, mode_of(CJ) and "%o" % mode_of(CJ)))
body = read(CJ)
seed(CJ + ".bak", "an older copy, same secrets")
os.chmod(CJ + ".bak", 0o644)
run_ctx = run_ctx._replace(apply=False)
code, dry, _ = case("cjbak-dry", {"a": {"project_path": d}})
dry_bak = mode_of(CJ + ".bak")
run_ctx = run_ctx._replace(apply=True)
code2, out, _ = case("cjbak-apply", {"a": {"project_path": d}})
said = lambda o: [l for l in o.splitlines() if ".claude.json.bak" in l]  # noqa: E731
current = "   ~/.claude.json -> already current"
check(code == 0 and code2 == 0 and dry_bak == 0o644 and mode_of(CJ + ".bak") == 0o600
      and mode_of(CJ) == 0o600 and read(CJ) == body
      and said(dry) == ["would chmod 600 ~/.claude.json.bak (it carries resolved secrets)"]
      and said(out) == ["chmod 600 ~/.claude.json.bak (it carries resolved secrets)"]
      and current in dry.splitlines() and current in out.splitlines(),
      "a current 600 ~/.claude.json beside a 644 .bak: .bak %o, dry-run %r, apply %r, current dry %s, apply %s"
      % (mode_of(CJ + ".bak"), said(dry), said(out), current in dry.splitlines(), current in out.splitlines()))
os.unlink(CJ + ".bak")
victim = os.path.join(TOY, "cjbak-victim")
seed(victim, "someone else's")
os.chmod(victim, 0o644)
os.symlink(victim, CJ + ".bak")
code, out, _ = case("cjbak-link", {"a": {"project_path": d}})
check(code == 0 and os.path.islink(CJ + ".bak") and mode_of(victim) == 0o644 and not said(out),
      "a ~/.claude.json.bak that is a link: exit %r, link kept %s, its target %o, lines %r"
      % (code, os.path.islink(CJ + ".bak"), mode_of(victim), said(out)))
# The file's own mode line, which nothing asserted before simplify-3 T3 folded its two
# chmod-and-print blocks into one loop: a 644 ~/.claude.json is named exactly, "would " on a
# dry-run only, and ends 600. A characterization: green on 1e34c0f and after. Control: with
# ClaudeJson.open's `if ctx.apply:` flipped to `if not ctx.apply:` it went red with
# "a 644 ~/.claude.json: mode 600 after the dry-run, 600 after apply, dry-run ['chmod 600
# ~/.claude.json (it carries resolved secrets)'], apply []" (the flipped dry-run had already
# chmodded it).
os.unlink(CJ + ".bak")
os.chmod(CJ, 0o644)
said = lambda o: [l for l in o.splitlines() if "chmod" in l and ".claude.json" in l]  # noqa: E731
run_ctx = run_ctx._replace(apply=False)
code, dry, _ = case("cjmode-dry", {"a": {"project_path": d}})
dry_mode = mode_of(CJ)
run_ctx = run_ctx._replace(apply=True)
code2, out, _ = case("cjmode-apply", {"a": {"project_path": d}})
check(code == 0 and code2 == 0 and dry_mode == 0o644 and mode_of(CJ) == 0o600
      and said(dry) == ["would chmod 600 ~/.claude.json (it carries resolved secrets)"]
      and said(out) == ["chmod 600 ~/.claude.json (it carries resolved secrets)"],
      "a 644 ~/.claude.json: mode %o after the dry-run, %o after apply, dry-run %r, apply %r"
      % (dry_mode, mode_of(CJ), said(dry), said(out)))

# 7. ... and only where git ignores it. Git never reads a .gitignore that is a symlink, wherever it
# points (git 2.55: "warning: unable to access '.gitignore': Too many levels of symbolic links"),
# so a line in its target proves nothing, and the target is never written through.
for label, target in (("outside the project", os.path.join(TOY, "elsewhere.gitignore")), ("inside it", "sub/gitignore")):
    reset_home()
    name = "gi-link-" + label.split()[0]
    d = os.path.join(TOY, name, "projects", "a")
    repo(d)
    real = target if os.path.isabs(target) else os.path.join(d, target)
    seed(real, "")
    os.symlink(target, os.path.join(d, ".gitignore"))
    code, out, _ = case(name, {"a": {}})
    toml = os.path.join(d, ".codex", "config.toml")
    ignored = subprocess.run(["git", "-C", d, "check-ignore", "-q", ".codex/config.toml"], capture_output=True).returncode == 0
    check(not os.path.lexists(toml) and "NOT written" in out,
          "a .gitignore symlinked %s: .codex/config.toml %s (git ignores it: %s)"
          % (label, "written" if os.path.lexists(toml) else "not written, but no 'NOT written' line", ignored))
    check(read(real) == "", "the .gitignore symlinked %s was written through: %r" % (label, read(real)))

# 8. lib.write_text and symlinks, one policy: a path that is a link has its target replaced and
# the link kept (scripts/tools/rotate_secret.py does the same); a .bak that is a link is never
# copied, chmodded or written through -- its target is someone else's file.
reset_home()
real_f, link = os.path.join(HOME, "real.json"), os.path.join(HOME, "link.json")
seed(real_f, "old")
os.symlink("real.json", link)
lib.write_text(link, "new", mode=0o600, backup=True)
check(os.path.islink(link) and read(real_f) == "new" and mode_of(real_f) == 0o600,
      "writing a symlinked path: link kept %s, target %r at %o" % (os.path.islink(link), read(real_f), mode_of(real_f)))
victim, p = os.path.join(TOY, "victim"), os.path.join(HOME, "p.json")
seed(victim, "someone else's")
os.chmod(victim, 0o644)
seed(p, "a")
os.symlink(victim, p + ".bak")
lib.write_text(p, "b", mode=0o600, backup=True)
check(mode_of(victim) == 0o644 and read(victim) == "someone else's" and os.path.islink(p + ".bak"),
      "a .bak symlinked to another file: that file %r at %o, link kept %s"
      % (read(victim), mode_of(victim), os.path.islink(p + ".bak")))
# That policy would let a planted link send a project's resolved secrets anywhere, a tracked
# file included (a `.codex/` ignore line does not even match a .codex that is a link), so the
# secret writer refuses a config.toml that does not resolve to <project>/.codex/config.toml.
for label, rel, to in (("config.toml", os.path.join(".codex", "config.toml"), os.path.join("..", "tracked.toml")),
                       (".codex", ".codex", "shared")):
    reset_home()
    name = "codex-link-" + label.strip(".").replace(".", "-")
    d = os.path.join(TOY, name, "projects", "a")
    repo(d)
    seed(os.path.join(d, "tracked.toml"), "x = 1\n")
    os.makedirs(os.path.join(d, "shared"))
    os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
    os.symlink(to, os.path.join(d, rel))
    code, out, _ = case(name, {"a": {}})
    check(read(os.path.join(d, "tracked.toml")) == "x = 1\n" and not os.listdir(os.path.join(d, "shared"))
          and os.path.islink(os.path.join(d, rel)) and "NOT written" in out,
          "a %s that is a symlink: tracked.toml %r, shared/ %r, link kept %s, output %r"
          % (label, read(os.path.join(d, "tracked.toml")), os.listdir(os.path.join(d, "shared")),
             os.path.islink(os.path.join(d, rel)), [l for l in out.splitlines() if "codex mcp" in l]))

# 9. A .gitignore that cannot be read (not UTF-8, a directory) is that project's error, reported,
# with nothing written under .codex/ or .agents/; it used to abort the run before the next profile.
for label, make in (("not UTF-8", lambda gi: open(gi, "wb").write(b"*.pyc\n\xff\xfe\n")), ("a directory", os.makedirs)):
    reset_home()
    name = "gi-bad-" + label.split()[-1]
    base = os.path.join(TOY, name, "projects")
    a, b = os.path.join(base, "a"), os.path.join(base, "b")
    repo(a)
    repo(b)
    make(os.path.join(a, ".gitignore"))
    code, out, _ = case(name, {"a": {}, "b": {}})
    check(code == 1 and ".gitignore unreadable" in out and not os.path.exists(os.path.join(a, ".codex"))
          and os.path.exists(os.path.join(b, ".codex", "config.toml")),
          "a .gitignore that is %s: exit %r, a's .codex %s, b's config.toml %s"
          % (label, code, os.path.exists(os.path.join(a, ".codex")), os.path.exists(os.path.join(b, ".codex", "config.toml"))))

# 10. A settings.json whose `env` is not an object is left as it is, said so on a '!' line of its
# own (forge/cli.py's CHANGED shows those at session start), and the rest of the user scope still
# runs. write_user_settings used to raise AttributeError on it, so the Jev extension,
# ~/.codex/hooks.json and Hindsight never ran. A warning alone never rewrites the file. The '!'
# line exits 1 (agent_config's exit rule); it exited 0 before the rule. The '!' line is the
# Jev setup's (skills/jev/scripts/setup.py settings_changes), so without that private skill there is no
# line and the exit is 0: the file is left as it is and the rest of the user scope still runs.
for label, env in (("null", None), ("a list", ["x"])):
    name = "env-" + label.split()[-1]
    reset_home()
    seed(hooks.USER_SETTINGS, json.dumps({"env": env, "theme": "dark"}))
    for run in ("first", "again"):
        code, out, _ = case("%s-%s" % (name, run), {"a": {}}, globals_=True)
        doc = json.loads(read(hooks.USER_SETTINGS))
        line = [l for l in out.splitlines() if "settings.json" in l]
        check(code == (1 if HAVE_JEV else 0) and doc.get("env") == env and doc.get("theme") == "dark"
              and ("   ! env is not an object, left alone" in out.splitlines()) == HAVE_JEV
              and any(l.startswith("   ~/.codex") or "codex-home/hooks.json" in l for l in out.splitlines())
              and (run == "first" or (len(line) == 1 and "(already current)" in line[0])),
              "settings.json with env %s, %s run: exit %r, env %r, settings lines %r"
              % (label, run, code, doc.get("env"), line))

# 11. A project's own skills are linked into .agents/skills only where git ignores .agents/. A
# .gitignore that is a symlink proves nothing (git reads none), and for a project that is not
# repo-owned the mirror used to ask only after making the links: they were created un-ignored and
# reported as a count with a SKIPPED suffix. Beside it, a plain .gitignore gets the line and links.
for label, link in (("a symlinked .gitignore", True), ("a plain .gitignore", False)):
    reset_home()
    name = "mirror-gi-" + ("link" if link else "plain")
    d = os.path.join(TOY, name, "projects", "a")
    repo(d)
    seed(os.path.join(d, ".claude", "skills", "s1", "SKILL.md"), "x")
    outside = os.path.join(TOY, name + ".gitignore")
    if link:
        seed(outside, "")
        os.symlink(outside, os.path.join(d, ".gitignore"))
    code, out, _ = case(name, {"a": {}})
    line = [l for l in out.splitlines() if "codex sees project skills" in l]
    agents = os.path.join(d, ".agents", "skills", "s1")
    if link:
        ok = not os.path.lexists(agents) and len(line) == 1 and "NOT linked" in line[0] and read(outside) == ""
    else:
        ok = (os.path.islink(agents) and ".agents/" in read(os.path.join(d, ".gitignore")).splitlines()
              and len(line) == 1 and "+1" in line[0] and "+gitignore" in line[0])
    check(ok, "%s: .agents/skills/s1 %s, lines %r" % (label, "linked" if os.path.lexists(agents) else "absent", line))

# 12. main() reads each profile once: for the relocation scope and again in the profile loop, a
# malformed one printed its '! could not read' warning twice.
reset_home()
code, out, _ = case("bad-profile", {"a": {}, "bad": "{not json"})
said = [l for l in out.splitlines() if "could not read" in l and "bad.claude.json" in l]
check(len(said) == 1, "a malformed profile: %d '! could not read' line(s), want 1: %r (exit %r)" % (len(said), said, code))

# 13. A profile with no project_path -- malformed, or written without one -- is skipped with a '!'
# line. It raised KeyError: 'project_path', and every later profile, the ~/.claude.json write and
# the user scope went with it.
reset_home()
code, out, dirs = case("no-path", {"a": {}, "bad": "{not json", "c": {}, "nopath": {"project_path": None}})
skipped = [l for l in out.splitlines() if l.lstrip().startswith("! no project_path")]
check(code == 1 and len(skipped) == 2 and "claude key: %s" % dirs["c"] in out and "== ~/.claude.json" in out,
      "profiles with no project_path: exit %r, %d skip line(s), later profile and ~/.claude.json %s"
      % (code, len(skipped), "reached" if "== ~/.claude.json" in out else "never reached"))

# 14. A config/secrets.json that does not exist is named missing, not "a COPY": a worktree has
# none (git ignores it), and the fix is the same link. Red before: the missing file was reported
# as "!! config/secrets.json is a COPY, not the symlink to credentials/secrets.json."
reset_home()
code, out, _ = case("no-secrets-link", {"a": {}}, secrets_link=False)
said = [l for l in out.splitlines() if "config/secrets.json" in l and l.startswith("!!")]
check(len(said) == 1 and "missing" in said[0] and "COPY" not in said[0],
      "no config/secrets.json: %r (exit %r)" % (said, code))

# 15. ~/.claude.json is written only if nobody wrote it since the run loaded it: every open Claude
# Code session saves it too, and our copy written over theirs drops what they just saved. The run
# has a change of its own to write (a's key), and the file's mtime moves while it generates.
reset_home()
raced = json.dumps({"projects": {"/elsewhere": {"allowedTools": ["x"]}}})
seed(CJ, raced)
real_overrides = skills.write_settings_local


def overrides_then_touch(*args):
    st = os.stat(CJ)
    os.utime(CJ, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))  # another session saved it
    return real_overrides(*args)


skills.write_settings_local = overrides_then_touch
code, out, _ = case("cj-raced", {"a": {}})
skills.write_settings_local = real_overrides
check(code == 0 and read(CJ) == raced
      and "   ~/.claude.json -> changed by another process while generating; not written, next run retries" in out.splitlines(),
      "~/.claude.json changed between load and commit: exit %r, %s, lines %r"
      % (code, "left alone" if read(CJ) == raced else "overwritten", [l for l in out.splitlines() if "~/.claude.json ->" in l]))

# 15b. A config/secrets.json that is a plain copy is named a COPY, with the keys credentials/ has
# and it lacks. The canonical file is read beside `cfg`, so this toy world never reaches the real
# credentials/ (running this against lib.ROOT would list the real key names). Red with the listing
# skipped (`if stale:` made `if False:`): the 'Missing here' line is absent.
reset_home()
code, out, _ = case("secrets-copy", {"a": {}}, secrets_link="copy")
said = [l for l in out.splitlines() if "COPY" in l or "Missing here" in l]
check(len(said) == 2 and said[1].strip() == "Missing here: ADDED_SINCE",
      "config/secrets.json a stale copy: %r (exit %r)" % (said, code))

# 16. A profile field of the wrong type (lib.PROFILE_FIELDS) is that profile's error, like a
# missing project_path: one '!' line naming the field, nothing written for it, exit 1, and the
# later profiles, ~/.claude.json and the user scope still run. Red before the table:
# `"servers": null` raised "TypeError: 'NoneType' object is not iterable" in the profile loop and
# `[5]` "AttributeError: 'int' object has no attribute 'startswith'" in check_retired_memory, a
# profile that is a JSON list raised "AttributeError: 'list' object has no attribute 'get'" in
# relocations_in_scope, before any profile ran, and `"project_path": 5` "TypeError: _path_normpath:
# path should be string, bytes or os.PathLike, not int" there too; `"frozen": "false"` froze the
# project with exit 0, and an env value 1 reached settings.local.json as a number with exit 0.
# Each crash also skipped the user scope ("stub(s) ... never ran").
for i, (label, bad, why) in enumerate((
        ("servers null", {"servers": None}, "servers is not a list of strings"),
        ("servers [5]", {"servers": [5]}, "servers is not a list of strings"),
        ("a JSON list", "[1]", "the profile is not a JSON object"),
        ("project_path 5", '{"project": "bad", "servers": [], "project_path": 5}', "project_path is not a string"),
        ("frozen 'false'", {"frozen": "false"}, "frozen is not a boolean"),
        ("an env value 1", {"env": {"X": 1}}, "env is not a JSON object of strings"))):
    reset_home()
    name = "bad-type-%d" % i
    code, out, dirs = case(name, {"bad": bad, "c": {}}, globals_=True)
    lines = out.splitlines()
    check(code == 1 and "   ! %s -- nothing written for this project" % why in lines
          and "claude key: %s" % dirs["c"] in out and "== ~/.claude.json (MCP servers, every profile) ==" in lines
          and "== Hindsight coding-agents (config + runtime) ==" in lines
          and not os.path.exists(os.path.join(TOY, name, "projects", "bad", ".claude")),
          "a profile with %s: exit %r, '!' lines %r, later profile %s, ~/.claude.json %s"
          % (label, code, [l for l in lines if l.lstrip().startswith("!")],
             "reached" if "claude key: %s" % dirs.get("c") in out else "never reached",
             "reached" if "== ~/.claude.json" in out else "never reached"))

# ... and its key is never relocated: the loop says nothing was written for it, so a relocation
# onto it would be a write the output denies. Red before: the run raised the TypeError above.
reset_home()
bad_dir = os.path.join(TOY, "bad-type-reloc", "projects", "bad")
seed(CJ, json.dumps({"projects": {"/old/bad": {"allowedTools": ["x"]}}}))
code, out, _ = case("bad-type-reloc", {"bad": {"servers": None}, "a": {}},
                    relocations=[{"from": "/old/bad", "to": bad_dir}])
got = json.loads(read(CJ))["projects"]
said = [l for l in out.splitlines() if l.lstrip().startswith("! relocation")]
check(code == 1 and "/old/bad" in got and bad_dir not in got and len(said) == 1
      and "servers is not a list of strings" in said[0],
      "a relocation onto a badly typed profile's key: exit %r, keys %r, relocation lines %r" % (code, sorted(got), said))

# 17. The Hindsight files are read as objects: a canonical config/hindsight-coding-agents.json that
# is valid JSON but not an object is an unreadable source, a '!' line with nothing rendered, and the
# runtime check says nothing about it; a rendered ~/.hindsight/coding-agent.json or
# .install-origin.json that is not one is no crash either. Red before: canonical 42
# raised "AttributeError: 'int' object has no attribute 'items'" in write_hindsight_config and
# "AttributeError: 'int' object has no attribute 'get'" in check_hindsight_runtime (true and [1]
# the same, with 'bool' and 'list'); a [1] rendered file raised "AttributeError: 'int' object has
# no attribute 'startswith'" and a [1] origin "AttributeError: 'list' object has no attribute 'get'".
# The runtime check appends its failures to the list it is given, as write_hindsight_config does,
# and returns only its status line: a missing staged runtime is one entry and None. Red before:
# the prefix was sniffed by sync.py, and every call here "raised TypeError:
# check_hindsight_runtime() takes 0 positional arguments but 1 was given".
def attempt(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return "raised %s: %s" % (type(e).__name__, e)


real_root = memory.ROOT
toy_root = os.path.join(TOY, "hindsight-shapes")
canon = os.path.join(toy_root, "config", "hindsight-coding-agents.json")
target = os.path.join(HOME, ".hindsight", "coding-agent.json")
memory.ROOT = toy_root
for text in ("42", "true", "[1]"):
    reset_home()
    seed(canon, text)
    errs = []
    line = attempt(real_write_hindsight_config, run_ctx, {}, errs)
    rt_errs = []
    runtime = attempt(real_check_hindsight_runtime, rt_errs)
    check(line == "   ! forge/config/hindsight-coding-agents.json is not a JSON object -- nothing rendered"
          and runtime is None and rt_errs == [] and not os.path.lexists(target),
          "a canonical hindsight config holding %s: config line %r, runtime %r, runtime errors %r, %s rendered"
          % (text, line, runtime, rt_errs, target.replace(HOME, "~") if os.path.lexists(target) else "nothing"))
reset_home()
seed(canon, json.dumps({"bank": "b", "autoInject": "recall"}))
seed(target, "[1]")
hook_js = os.path.join(HOME, ".hindsight", "coding-agents", "dist", "claude-hook.js")
seed(hook_js, "autoInject")
seed(os.path.join(HOME, ".hindsight", "coding-agents", ".install-origin.json"), "[1]")
line = attempt(real_write_hindsight_config, run_ctx, {}, [])
rt_errs = []
runtime = attempt(real_check_hindsight_runtime, rt_errs)
os.remove(hook_js)
gone_errs = []
gone = attempt(real_check_hindsight_runtime, gone_errs)
check(line == "   config -> ~/.hindsight/coding-agent.json (replaced: was not a JSON object)"
      and json.loads(read(target)) == {"bank": "b", "autoInject": "recall"}
      and runtime == "   runtime -> ~/.hindsight/coding-agents honours autoInject 'recall' (unknown origin)"
      and rt_errs == [] and gone is None
      and gone_errs == ["hindsight: config asks for autoInject 'recall' but the staged runtime is missing "
                        "(~/.hindsight/coding-agents/dist/claude-hook.js). Memory injection is not running."],
      "a rendered config and an install origin holding [1]: config line %r, runtime %r, runtime errors %r; "
      "with the staged runtime gone: runtime %r, runtime errors %r" % (line, runtime, rt_errs, gone, gone_errs))
memory.ROOT = real_root

# 18. A hook entry whose "command" is not a string is malformed: dropped, and counted, in an event
# forge owns; left as it is in a foreign one, which reconcile never touches. Red before:
# "raised TypeError: argument of type 'NoneType' is not a container or iterable" for
# both agents, from the ward loop's `mark in h.get("command", "")`.
for agent in (hooks.CLAUDE,):
    ev = next(row[0] for row in hooks.USER_HOOKS if agent in row[5])
    foreign = [{"hooks": [{"type": "command", "command": None}, {"type": "command", "command": 5}]}]
    doc = {"hooks": {ev: [{"hooks": [{"type": "command", "command": None}, {"type": "command", "command": 5},
                                     {"type": "command"}]}],
                     "Foreign": json.loads(json.dumps(foreign))}}
    notes = attempt(hooks.reconcile, doc, agent)
    left = [h.get("command") for g in (doc["hooks"].get(ev) or []) for h in g.get("hooks", [])]
    check(isinstance(notes, list) and any(n.startswith("dropped 2 malformed") and n.endswith(" of " + ev) for n in notes)
          and not [c for c in left if c is not None and not isinstance(c, str)] and None in left
          and doc["hooks"]["Foreign"] == foreign,
          "%s hooks with a non-string command: notes %r, %s commands left %r, Foreign %r"
          % (agent, notes, ev, left, doc["hooks"].get("Foreign")))

# 19. A project whose .agents (or .agents/skills) is a regular file gets no links and a '!' line,
# in a dry-run as in an --apply: the file and the .gitignore are left alone and the next profile
# still runs. Red before: --apply "raised NotADirectoryError: [Errno 20] Not a
# directory: '.../.agents/skills'" (".agents/skills" a file: "raised FileExistsError: [Errno 17]
# File exists"), and the dry-run promised "(1 skill(s), +1) ... [dry-run]" for links it could not make.
for i, (sub, apply) in enumerate(((".agents", True), (".agents", False), (os.path.join(".agents", "skills"), True))):
    reset_home()
    name = "agents-file-%d" % i
    d = os.path.join(TOY, name, "projects", "a")
    repo(d)
    seed(os.path.join(d, ".claude", "skills", "s1", "SKILL.md"), "x")
    seed(os.path.join(d, sub), "not a directory")
    run_ctx = run_ctx._replace(apply=apply)
    code, out, dirs = case(name, {"a": {}, "b": {}})
    run_ctx = run_ctx._replace(apply=True)
    gi = os.path.join(d, ".gitignore")
    want_line = "   ! codex sees project skills -> %s NOT linked (%s is not a directory)" % (
        os.path.join(d, ".agents", "skills"), sub)
    check(want_line in out.splitlines() and read(os.path.join(d, sub)) == "not a directory"
          and (not os.path.exists(gi) or ".agents/" not in read(gi).splitlines())
          and "claude key: %s" % dirs.get("b") in out,
          "%s a regular file, %s: exit %r, mirror lines %r, .gitignore %r"
          % (sub, "--apply" if apply else "dry-run", code,
             [l for l in out.splitlines() if "codex sees" in l] or out[-300:],
             read(gi) if os.path.exists(gi) else None))

# 20. settings.local.json is generator-owned: a profile that stops trimming (skills_keep and
# plugins_keep removed) loses the skillOverrides and enabledPlugins it was given, as it already
# lost env, while what a session approved stays. Red before: a bare profile's
# stale keys all stayed, "keys ['enabledPlugins', 'env', 'permissions', 'skillOverrides']" with
# no overrides line, because it returned before reading the file; with an env of its own, env
# was replaced and "keys ['enabledPlugins', 'env', 'permissions', 'skillOverrides']" still; one
# trimming skills with no plugins_keep kept the stale plugin map, "keys ['enabledPlugins',
# 'permissions', 'skillOverrides']", and said "plugins unchanged". The second run's check was
# seen to fail with the new early `return None` deleted: "a bare profile, second run: exit 0,
# overrides lines ['   overrides -> .../settings.local.json (untrimmed (pass-through only))
# (already current)']".
STALE = {"skillOverrides": {"gsd-x": "off"}, "enabledPlugins": {"p@x": False}, "env": {"OLD": "1"},
         "permissions": {"allow": ["Bash(ls:*)"]}}
for label, prof, keys, said in (
        ("a bare profile", {}, ["permissions"], "enabledPlugins and skillOverrides removed, env removed"),
        ("a profile with env", {"env": {"K": "v"}}, ["env", "permissions"], "enabledPlugins and skillOverrides removed"),
        ("a profile trimming skills only", {"skills_keep": []}, ["permissions", "skillOverrides"],
         "plugins untrimmed, skills off 0, kept-global 0, enabledPlugins removed, env removed")):
    reset_home()
    name = "untrim-" + label.split()[-1]
    d = os.path.join(TOY, name, "projects", "a")
    slp = os.path.join(d, ".claude", "settings.local.json")
    seed(slp, json.dumps(STALE))
    code, out, _ = case(name, {"a": prof})
    doc = json.loads(read(slp))
    line = [l for l in out.splitlines() if "overrides ->" in l]
    check(code == 0 and sorted(doc) == keys and doc["permissions"] == STALE["permissions"]
          and doc.get("env", {"K": "v"}) == {"K": "v"} and len(line) == 1 and said in line[0],
          "%s over a trimmed settings.local.json: exit %r, keys %r, overrides lines %r" % (label, code, sorted(doc), line))
    code, out, _ = case(name + "-again", {"a": dict(prof, project_path=d)})
    line = [l for l in out.splitlines() if "overrides ->" in l]
    check(code == 0 and json.loads(read(slp)) == doc and (line == [] if not prof else "(already current)" in line[0]),
          "%s, second run: exit %r, overrides lines %r" % (label, code, line))

# 21. A profile with no env still gives Codex MCPORTER_CONFIG, under this HOME: the value was the
# author's home spelled out. Red before: the toy config.toml said
# "MCPORTER_CONFIG" = "<the author's home>/.config/mcporter/mcporter.json".
reset_home()
d = os.path.join(TOY, "mcporter-home", "projects", "a")
repo(d)
code, out, _ = case("mcporter-home", {"a": {}})
toml = os.path.join(d, ".codex", "config.toml")
body = read(toml) if os.path.exists(toml) else ""
said = [l for l in body.splitlines() if "MCPORTER_CONFIG" in l]
check(code == 0 and said == ['"MCPORTER_CONFIG" = "%s"' % os.path.join(HOME, ".config", "mcporter", "mcporter.json")],
      "a profile with no env: exit %r, MCPORTER_CONFIG lines %r" % (code, said))

# 22. A .codex/config.toml that is not UTF-8 is rewritten 0600, and the profiles after it still
# run. The unchanged-content read raised UnicodeDecodeError, which is not lib.Unreadable, so the
# traceback skipped every later profile, the ~/.claude.json commit and the user scope.
# Red before: "a non-UTF-8 config.toml: exit "raised UnicodeDecodeError: 'utf-8'
# codec can't decode byte 0xff in position 0: invalid start byte", mode 644, a's lines [], b's
# config.toml False".
reset_home()
a, b = (os.path.join(TOY, "codex-latin", "projects", n) for n in "ab")
repo(a)
repo(b)
toml_a, toml_b = (os.path.join(p, ".codex", "config.toml") for p in (a, b))
os.makedirs(os.path.dirname(toml_a))
with open(toml_a, "wb") as f:
    f.write(b"\xff")
os.chmod(toml_a, 0o644)
code, out, _ = case("codex-latin", {"a": {}, "b": {}})
said = [l for l in out.splitlines() if "codex mcp -> " + lib.short(toml_a) in l]
check(code == 0 and mode_of(toml_a) == 0o600 and len(said) == 1 and said[0].endswith("(updated)")
      and os.path.exists(toml_b) and read(toml_a) == read(toml_b),
      "a non-UTF-8 config.toml: exit %r, mode %o, a's lines %r, b's config.toml %s"
      % (code, mode_of(toml_a) or 0, said, os.path.exists(toml_b)))

# 23. A CRLF .codex/config.toml is rewritten to the generated LF text: read with universal
# newlines it compared equal, and was "(already current)" forever.
# Red before: "a CRLF config.toml: exit 0, lines ['   codex mcp -> .../config.toml
# (0 servers) (already current)'], LF on disk False".
reset_home()
d = os.path.join(TOY, "codex-crlf", "projects", "a")
repo(d)
toml = os.path.join(d, ".codex", "config.toml")
code, out, _ = case("codex-crlf", {"a": {}})
body = read(toml)
with open(toml, "wb") as f:
    f.write(body.replace("\n", "\r\n").encode())
code, out, _ = case("codex-crlf-again", {"a": {"project_path": d}})
said = [l for l in out.splitlines() if "codex mcp" in l]
with open(toml, "rb") as f:
    lf = f.read() == body.encode()
check(code == 0 and len(said) == 1 and said[0].endswith("(updated)") and lf,
      "a CRLF config.toml: exit %r, lines %r, LF on disk %s" % (code, said, lf))

# 24. A registry with no servers object refuses the run: one '!' line, exit 1, nothing written.
# lib.read_json turns `{broken` (and a missing file) into {}, so every server the profiles list
# was "not in registry", every project's mcpServers became {} and its .codex/config.toml held zero
# servers, and the run exited 0 -- a session start did it to its own project, `forge sync --apply`
# to all of them. A `[]` registry raised at the `.get` in mcp.load_inputs.
# Red before: "a registry holding '{broken': exit 0, '!' line False, ~/.claude.json
# kept False (a's mcpServers {}), .codex/config.toml kept False", the same for '{}', '{"servers":
# []}' and a missing registry, and "a registry holding '[]': exit "raised AttributeError: 'list'
# object has no attribute 'get'", '!' line False, ...".
# A readable {"servers": {}} still runs: every other case here seeds exactly that.
REFUSE = "! config/mcp-registry.json has no servers object (unreadable, missing or malformed) -- nothing written"
for i, text in enumerate(("{broken", "[]", "{}", '{"servers": []}', False)):
    reset_home()
    name = "registry-refused-%d" % i
    d = os.path.join(TOY, name, "projects", "a")
    repo(d)
    toml = os.path.join(d, ".codex", "config.toml")
    seed(toml, "# an older config.toml\n")
    seed(CJ, json.dumps({"projects": {mcp.project_key(d): {"mcpServers": {"s1": {"command": "old"}}}}}))
    before = (read(CJ), read(toml))
    code, out, _ = case(name, {"a": {"servers": ["s1"]}}, registry=text)
    ms = json.loads(read(CJ)).get("projects", {}).get(mcp.project_key(d), {}).get("mcpServers")
    what = "a missing registry" if text is False else "a registry holding %r" % text
    check(code == 1 and REFUSE in out.splitlines() and (read(CJ), read(toml)) == before,
          "%s: exit %r, '!' line %s, ~/.claude.json kept %s (a's mcpServers %r), .codex/config.toml kept %s"
          % (what, code, REFUSE in out.splitlines(), read(CJ) == before[0], ms, read(toml) == before[1]))

# 25. A relocations file of the wrong shape is read as no relocations, after one '!' line naming
# the file and the shape, and the run goes on and exits 1 under agent_config's exit rule -- as an
# unreadable one does after lib.read_json's "could not read" line. Both exited 0 until the rule.
# A bad entry is skipped alone: the valid one beside it still moves its key.
# Red before, every run raised before any profile: "relocations '[]': exit "raised
# AttributeError: 'list' object has no attribute 'get'", lines [], /old/a kept True, a's key
# written False", the same for '42' and 'null'; '{"relocations": 5}' "raised TypeError: 'int'
# object is not iterable" (and 'NoneType' for null); "relocation entry '/old/x': exit "raised
# AttributeError: 'str' object has no attribute 'get'", lines [], the valid entry beside it
# applied False", the same for 5 and None; and {'from': 5, ...} "raised TypeError: _path_normpath:
# path should be string, bytes or os.PathLike, not int" (not list, for a list `to`). The control
# below passes before and after; with load_relocations' `doc.get("relocations", [])` made
# `doc.get("relocations")` it fails, "an unparsable relocations file: exit 0, lines ['! could not
# read <toy>/project-relocations.json: Expecting property name ...', '! config/project-relocations
# .json: `relocations` is null, not a list -- no relocation applied']".
RELOC = "! config/project-relocations.json"
for i, (text, want) in enumerate((
        ("[]", "! config/project-relocations.json holds a list, not an object -- no relocation applied"),
        ("42", "! config/project-relocations.json holds a number, not an object -- no relocation applied"),
        ("null", "! config/project-relocations.json holds null, not an object -- no relocation applied"),
        ('{"relocations": 5}',
         "! config/project-relocations.json: `relocations` is a number, not a list -- no relocation applied"),
        ('{"relocations": null}',
         "! config/project-relocations.json: `relocations` is null, not a list -- no relocation applied"))):
    reset_home()
    name = "reloc-shape-%d" % i
    a = os.path.join(TOY, name, "projects", "a")
    seed(CJ, json.dumps({"projects": {"/old/a": {"allowedTools": ["y"]}}}))
    code, out, _ = case(name, {"a": {}}, relocations=text)
    said = [l.strip() for l in out.splitlines() if l.strip().startswith(RELOC)]
    got = json.loads(read(CJ))["projects"]
    check(code == 1 and said == [want] and "/old/a" in got and a in got,
          "relocations %r: exit %r, lines %r, /old/a kept %s, a's key written %s"
          % (text, code, said, "/old/a" in got, a in got))

for i, (bad, want) in enumerate((
        ("/old/x", "! config/project-relocations.json: relocations[0] is a string, not an object -- skipped"),
        (5, "! config/project-relocations.json: relocations[0] is a number, not an object -- skipped"),
        (None, "! config/project-relocations.json: relocations[0] is null, not an object -- skipped"),
        ({"from": 5, "to": "/new/x"},
         "! config/project-relocations.json: relocations[0] has a `from` that is a number, not a path -- skipped"),
        ({"from": "/old/x", "to": ["/new/x"]},
         "! config/project-relocations.json: relocations[0] has a `to` that is a list, not a path -- skipped"))):
    reset_home()
    name = "reloc-entry-%d" % i
    a = os.path.join(TOY, name, "projects", "a")
    seed(CJ, json.dumps({"projects": {"/old/a": {"allowedTools": ["y"]}}}))
    code, out, _ = case(name, {"a": {}}, relocations=json.dumps({"relocations": [bad, {"from": "/old/a", "to": a}]}))
    said = [l.strip() for l in out.splitlines() if l.strip().startswith(RELOC)]
    got = json.loads(read(CJ))["projects"]
    moved = "/old/a" not in got and got.get(a, {}).get("allowedTools") == ["y"]
    check(code == 1 and said == [want] and moved,
          "relocation entry %r: exit %r, lines %r, the valid entry beside it applied %s" % (bad, code, said, moved))

# Control: an unparsable file keeps its one lib.read_json line, and gets no second line from the
# shape check -- the path the shapes above were made consistent with. It exits 1: that line is
# printed inside lib, and agent_config's rule reads the run's whole stdout, not only the lines
# sync.py prints itself (simplify-2 T11 item 6). On 0ad2214, whose hand-set flags saw only
# sync.py's own lines, it was "reloc-broken: exit 0 with a '!' line, first '  ! could not read
# <toy>/reloc-broken/config/project-relocations.json: Expecting property name enclosed in double
# quotes: line 1 column 2 (char 1)' -- the exit rule". With lib.Rule.write's `self.failed = ...`
# line deleted, 103 checks fail here (re-run after simplify-3 T1 moved the class from sync.py to
# lib.py: still 103 of 235), this one with "an unparsable relocations file: exit 0, lines
# ['! could not read <toy>/reloc-broken/config/project-relocations.json: Expecting property name
# enclosed in double quotes: line 1 column 2 (char 1)']".
reset_home()
code, out, _ = case("reloc-broken", {"a": {}}, relocations="{broken")
said = [l.strip() for l in out.splitlines() if "project-relocations.json" in l]
check(code == 1 and len(said) == 1 and said[0].startswith("! could not read "),
      "an unparsable relocations file: exit %r, lines %r" % (code, said))

# 26. A canonical config/hindsight-coding-agents.json with an empty apiToken renders with no secrets at
# all: the bank lives in the laptop's coding server at 127.0.0.1:9077, which
# takes no bearer, so HINDSIGHT_API_TOKEN can leave credentials/ without the generator failing.
# Dry-run against the toy HOME: nothing is written, and the real ~/.hindsight is never read.
# Red before (e2388fb): "the real canonical hindsight config with secrets = {}: errors ["server
# 'hindsight-coding-agents' config apiToken -> secret HINDSIGHT_API_TOKEN is EMPTY/missing"], line
# '   ! secret unresolved -- ~/.hindsight/coding-agent.json NOT written', nothing rendered".
# The file is the fixture's (a copy_engine copy has no config/hindsight-coding-agents.json: red there
# before, M1, "FileNotFoundError" at the read of it). Where this checkout has its own, the rest of the
# case runs on that one too: the connection itself, top-level apiUrl/apiToken name 9077 with no token,
# bankId stays the one bank, and there is no `banks` section for it (the doctor's per-bank checks iterate
# mapPathToBank, where the default bank is not, so a section would be a second copy of the URL nobody reads). No
# text in the file names the destroyed containers, Hermes or the old tailnet host. Red before (e2388fb): "the real
# canonical hindsight config: apiUrl '<the tailnet URL>', apiToken
# '${HINDSIGHT_API_TOKEN}', bankId '<bank>', banks.<bank> False, dead names in ['_bankId_doc',
# '_banks_doc', '_doc', '_mapPathToBank_doc', '_retainTags_doc', 'apiToken', 'apiUrl']".
reset_home()
assert memory.ROOT == os.path.dirname(os.path.dirname(os.path.abspath(__file__))), memory.ROOT
REAL_CANON = os.path.join(memory.ROOT, "config", "hindsight-coding-agents.json")
canon_root = os.path.join(TOY, "canon-fixture")
seed(os.path.join(canon_root, "config", "hindsight-coding-agents.json"), read(os.path.join(FIXTURES, "hindsight-coding-agents.json")))
for label, root26 in (("the fixture's", canon_root), ("this machine's", memory.ROOT)):
    if root26 == memory.ROOT and not os.path.exists(REAL_CANON):
        print("NOT RUN: this machine's canonical hindsight config -- no config/hindsight-coding-agents.json in this checkout")
        continue
    real_root26, memory.ROOT = memory.ROOT, root26
    run_ctx = run_ctx._replace(apply=False)
    errs = []
    try:
        line = real_write_hindsight_config(run_ctx, {}, errs)
    finally:
        memory.ROOT = real_root26
    run_ctx = run_ctx._replace(apply=True)
    target = os.path.join(HOME, ".hindsight", "coding-agent.json")
    check(not errs and "NOT written" not in line and not line.lstrip().startswith("!")
          and not os.path.lexists(target),
          "%s canonical hindsight config with secrets = {}: errors %r, line %r, %s rendered"
          % (label, errs, line, "something" if os.path.lexists(target) else "nothing"))
if os.path.exists(REAL_CANON):
    real_canon = json.loads(read(REAL_CANON))
    DEAD = re.compile(r"ts\\.net|\bCT ?11[13]\b|Hermes|HINDSIGHT_API_TOKEN")
    dead = sorted(k for k, v in real_canon.items() if DEAD.search(json.dumps(v)))
    check(real_canon.get("apiUrl") == "http://127.0.0.1:9077" and real_canon.get("apiToken") == ""
          and bool(real_canon.get("bankId")) and real_canon.get("bankId") not in (real_canon.get("banks") or {})
          and not dead,
          "the real canonical hindsight config: apiUrl %r, apiToken %r, bankId %r, bank in banks %s, "
          "dead names in %r" % (real_canon.get("apiUrl"), real_canon.get("apiToken"),
                                real_canon.get("bankId"), real_canon.get("bankId") in (real_canon.get("banks") or {}), dead))

    # S5 of the memory design doc: the default bank is recalled with every fact type, so a
    # fresh save is found before consolidation. The hook and the recall wrapper read the TOP-LEVEL key.
    want = ["observation", "world", "experience"]
    got = (real_canon.get("recallOptions") or {}).get("types")
    doc = real_canon.get("_recallOptions_doc", "")
    OLD_DOC = "keeps the runtime default (observations only)"
    check(got == want and OLD_DOC not in doc,
          "the real canonical recallOptions: %r, doc still says the bank keeps observations only: %s"
          % (real_canon.get("recallOptions"), OLD_DOC in doc))

# 27. A registry server's top-level keys that start with '_' are notes, never config: none reaches
# ~/.claude.json (plan step 2). The registry carries `_doc` on twelve servers and `_deny_tools_doc`
# on one, and they were written into every project's mcpServers entry; only `_headers_present` was
# popped, by name. `deny_tools` is still consumed (permissions.deny), and real keys are kept.
# Red before: "exit 0, '_' keys in the written mcpServers entry: ['_deny_tools_doc',
# '_doc', '_note'], real keys kept True" and "resolved_server kept ['_deny_tools_doc', '_doc',
# '_note']" (`_headers_present` was already gone: the by-name pop).
reset_home()
d27 = os.path.join(TOY, "underscore", "projects", "a")
repo(d27)
REG27 = {"servers": {"s1": {"command": "run", "args": ["x"], "env": {"K": "v"}, "deny_tools": ["t"],
                            "_doc": "a note", "_deny_tools_doc": "why", "_note": "n",
                            "_headers_present": True}}}
code, out, _ = case("underscore", {"a": {"servers": ["s1"]}}, registry=json.dumps(REG27))
ent = (json.loads(read(CJ)).get("projects", {}).get(mcp.project_key(d27), {}).get("mcpServers") or {}).get("s1") or {}
under = sorted(k for k in ent if k.startswith("_"))
check(code == 0 and not under and ent.get("command") == "run" and ent.get("args") == ["x"]
      and ent.get("env") == {"K": "v"} and "deny_tools" not in ent,
      "exit %r, '_' keys in the written mcpServers entry: %r, real keys kept %s"
      % (code, under, ent.get("command") == "run" and ent.get("env") == {"K": "v"}))
direct = mcp.resolved_server("s1", REG27["servers"]["s1"], {}, [])
check(sorted(k for k in direct if k.startswith("_")) == [] and "deny_tools" not in direct
      and direct.get("command") == "run",
      "resolved_server kept %r" % sorted(k for k in direct if k.startswith("_")))

# 27b. The .mcp.json approval keys (enabledMcpjsonServers, enableAllProjectMcpServers) belong in
# a project's settings.local.json, where Claude Code reads them; in ~/.claude.json they did
# nothing, and Claude Code removes them from a project entry itself. forge put them back on every
# run, so a session start said `~/.claude.json -> wrote` and the dry-run right after said `would
# write`. Now ClaudeJson.project neither adds nor removes them. Red before: see the commit body.
reset_home()
d27b = os.path.join(TOY, "approvalkeys", "projects", "a")
repo(d27b)
P27B = {"servers": [], "enableAllProjectMcpServers": True}
code, out, _ = case("approvalkeys", {"a": P27B})
ent = json.loads(read(CJ))["projects"][mcp.project_key(d27b)]
for k in ("enabledMcpjsonServers", "enableAllProjectMcpServers"):
    ent.pop(k, None)  # what Claude Code 2.1.294 does to a project entry
seed(CJ, json.dumps({"projects": {mcp.project_key(d27b): ent}}))
before = read(CJ)
code, out, _ = case("approvalkeys-again", {"a": dict(P27B, project_path=d27b)})
back = sorted(k for k in json.loads(read(CJ))["projects"][mcp.project_key(d27b)]
              if k in ("enabledMcpjsonServers", "enableAllProjectMcpServers"))
line = [l for l in out.splitlines() if "~/.claude.json ->" in l]
check(code == 0 and line == ["   ~/.claude.json -> already current"] and read(CJ) == before and not back,
      "an entry without the two keys, rerun: exit %r, ~/.claude.json line %r, keys back %r" % (code, line, back))
# Neither does it remove them: a session may have set them, and Claude Code removes them itself.
ent = json.loads(read(CJ))["projects"][mcp.project_key(d27b)]
ent["enabledMcpjsonServers"], ent["enableAllProjectMcpServers"] = ["sess"], False
seed(CJ, json.dumps({"projects": {mcp.project_key(d27b): ent}}))
before = read(CJ)
code, out, _ = case("approvalkeys-held", {"a": dict(P27B, project_path=d27b, mcpjson_approved=["x"])})
now = json.loads(read(CJ))["projects"][mcp.project_key(d27b)]
line = [l for l in out.splitlines() if "~/.claude.json ->" in l]
check(code == 0 and line == ["   ~/.claude.json -> already current"] and read(CJ) == before
      and now.get("enabledMcpjsonServers") == ["sess"] and now.get("enableAllProjectMcpServers") is False,
      "an entry holding the keys, rerun: exit %r, ~/.claude.json line %r, enabledMcpjsonServers %r (want ['sess'])"
      % (code, line, now.get("enabledMcpjsonServers")))

# 27c. enableAllProjectMcpServers reaches settings.local.json whenever the profile declares it, with or
# without `mcpjson_approved`: it was written only beside the approved list, so the profiles that
# declare it alone would have it nowhere once ~/.claude.json stopped carrying it. enabledMcpjsonServers
# stays written only with `mcpjson_approved`. Negative controls: a profile that does not declare the key,
# or declares false, gets no `true`.
for label, prof, want, summary in (
        ("a bare profile with the key", {"enableAllProjectMcpServers": True}, True, "(ALL: on)"),
        ("a trimmed profile with the key", {"skills_keep": [], "enableAllProjectMcpServers": True}, True, "(ALL: on)"),
        ("a trimmed profile with the key false", {"skills_keep": [], "enableAllProjectMcpServers": False}, False, None),
        ("a trimmed profile without the key", {"skills_keep": []}, None, None),
        ("an approved list and the key", {"mcpjson_approved": ["x"], "enableAllProjectMcpServers": True}, True, "(ALL: on)"),
        ("an approved list, no key", {"mcpjson_approved": ["x"]}, None, None)):
    reset_home()
    name = "allkey-" + re.sub(r"\W+", "-", label)
    code, out, dirs = case(name, {"a": prof})
    slp = os.path.join(dirs["a"], ".claude", "settings.local.json")
    doc = json.loads(read(slp)) if os.path.exists(slp) else {}
    line = [l for l in out.splitlines() if "overrides ->" in l]
    check(code == 0 and doc.get("enableAllProjectMcpServers") == want
          and ("enabledMcpjsonServers" in doc) == ("mcpjson_approved" in prof)
          and ((summary is None and not any("(ALL: on)" in l for l in line))
               or (summary is not None and len(line) == 1 and summary in line[0])),
          "%s: exit %r, enableAllProjectMcpServers %r (want %r), keys %r, overrides lines %r"
          % (label, code, doc.get("enableAllProjectMcpServers"), want, sorted(doc), line))

# 28. reconcile() owns a marker's entries on EVERY event, per agent: an entry carrying the marker of one
# of this agent's rows, on an event where none of this agent's rows with that marker lives, is dropped
# with a note naming the event. Without it, deleting the UserPromptSubmit gsd_output_discipline.py row
# (T1, docs/hooks-phase-design.md) leaves the old entry firing on every prompt forever, because
# reconcile never touched an event that has no row. Controls in the same case: a foreign entry beside
# it, and the PostToolUse and Stop discipline entries, left as they were; a second run says nothing. Red before:
# "notes ['dropped 1 stale UserPromptSubmit gsd_output_discipline.py'], UserPromptSubmit still carries
# ['python3 .../hooks/gsd_output_discipline.py'], PreCompact left ['python3 .../hooks/gsd_output_discipline.py',
# 'some-foreign-hook --flag']" (the UserPromptSubmit row still existed, so the stray copy was only a
# duplicate; the PreCompact entry, on an event with no row, survived).
GSD_CMD = "python3 %s/gsd_output_discipline.py" % hooks.HOOK_DIR
for agent in (hooks.CLAUDE,):
    doc = {"hooks": {}}
    attempt(hooks.reconcile, doc, agent)  # every row in place; the controls below start from here
    keep_post = json.loads(json.dumps(doc["hooks"]["PostToolUse"]))
    keep_stop = json.loads(json.dumps(doc["hooks"]["Stop"]))
    stray = {"type": "command", "command": GSD_CMD, "timeout": 10}
    foreign = {"type": "command", "command": "some-foreign-hook --flag", "timeout": 5}
    doc["hooks"].setdefault("UserPromptSubmit", []).append({"hooks": [dict(stray)]})
    doc["hooks"]["PreCompact"] = [{"hooks": [dict(stray), dict(foreign)]}]
    notes = attempt(hooks.reconcile, doc, agent)
    cmds = lambda ev: [h.get("command") for g in doc["hooks"].get(ev) or [] for h in g.get("hooks", [])]
    again = attempt(hooks.reconcile, doc, agent)
    gsd_prompt = [c for c in cmds("UserPromptSubmit") if "gsd_output_discipline.py" in c]
    check(notes == ["dropped 1 gsd_output_discipline.py (UserPromptSubmit: no row on this event)",
                    "dropped 1 gsd_output_discipline.py (PreCompact: no row on this event)"]
          and gsd_prompt == [] and cmds("PreCompact") == ["some-foreign-hook --flag"]
          and doc["hooks"]["PostToolUse"] == keep_post and doc["hooks"]["Stop"] == keep_stop
          and again == [],
          "%s: notes %r, UserPromptSubmit still carries %r, PreCompact left %r, PostToolUse kept %s, "
          "Stop kept %s, second run %r"
          % (agent, notes, gsd_prompt, cmds("PreCompact"), doc["hooks"]["PostToolUse"] == keep_post,
             doc["hooks"]["Stop"] == keep_stop, again))

# 29. Native deny rules for secret files (T3, docs/hooks-phase-design.md): write_user_settings unions
# twenty-three Read rules (nine of forge's own, fourteen machine credential stores) into
# ~/.claude/settings.json permissions.deny, in order, after whatever is there.
# The design's six paths, the ~/.hindsight/ one as three rules, because T0 measured that
# Read(~/.hindsight/*) also refused a file one level down (hs/sub/ok.txt: "File is in a directory that is
# denied by your permission settings.") while *.json*, *.token and *.env left subdirectories readable.
# The expected list is spelled out here, not taken from hooks.py.
# Controls: a foreign deny rule (and `allow`, `defaultMode`) survives in its place; one of our rules
# already present is not added twice and the note counts only what was added; a permissions value that
# is not an object, or a deny that is not a list, is left alone with a '!' line; the second run says
# nothing. Red before: see the commit body for the failure messages.
# The fourteen machine stores take the strings of a frozen project's tracked .claude/settings.json where it has
# them (npm, gh, git-credentials, Vercel x2, Supabase, aws credentials, kube, docker, ssh id_rsa and
# id_ed25519); ~/.aws/config, id_ecdsa and id_dsa are forge's additions. SSH keys are spelled by name and
# not as ~/.ssh/id_*, which would also refuse the readable id_*.pub.
R = hooks.ROOT
DENY = ["Read(/%s/credentials/**)" % R, "Read(/%s/config/secrets*)" % R, "Read(~/.claude.json*)",
        "Read(~/.hindsight/*.json*)", "Read(~/.hindsight/*.token)", "Read(~/.hindsight/*.env)",
        "Read(~/.hindsight/profiles/*.env*)", "Read(//**/.mcp.json)", "Read(//**/.codex/config.toml)",
        "Read(~/.npmrc)", "Read(~/.config/gh/hosts.yml)", "Read(~/.git-credentials)",
        "Read(~/.local/share/com.vercel.cli/**)", "Read(~/.vercel/auth.json)", "Read(~/.supabase/access-token)",
        "Read(~/.aws/credentials)", "Read(~/.aws/config)", "Read(~/.kube/config)", "Read(~/.docker/config.json)",
        "Read(~/.ssh/id_rsa)", "Read(~/.ssh/id_ed25519)", "Read(~/.ssh/id_ecdsa)", "Read(~/.ssh/id_dsa)"]
reset_home()
seed(hooks.USER_SETTINGS, json.dumps({"theme": "dark"}))
for run in ("first", "again"):
    code, out, _ = case("deny-" + run, {"a": {}}, globals_=True)
    doc = json.loads(read(hooks.USER_SETTINGS))
    line = [l for l in out.splitlines() if "settings.json" in l]
    perms = doc.get("permissions")
    check(code == 0 and isinstance(perms, dict) and perms.get("deny") == DENY and doc.get("theme") == "dark"
          and len(DENY) == 23 and len(set(DENY)) == 23 and len(line) == 1
          and (("permissions.deny +23 (secret files)" in line[0]) if run == "first"
               else ("(already current)" in line[0] and "23 secret-read deny rules" in line[0])),
          "no permissions, %s run: exit %r, permissions %r, line %r" % (run, code, perms, line))
reset_home()
seed(hooks.USER_SETTINGS, json.dumps({"permissions": {"deny": ["Read(//x/foreign)", DENY[2]], "allow": ["Bash(ls)"],
                                                      "defaultMode": "auto"}}))
code, out, _ = case("deny-foreign", {"a": {}}, globals_=True)
doc = json.loads(read(hooks.USER_SETTINGS))
line = [l for l in out.splitlines() if "settings.json" in l]
perms = doc.get("permissions") or {}
check(code == 0 and perms.get("deny") == ["Read(//x/foreign)", DENY[2]] + [r for r in DENY if r != DENY[2]]
      and perms.get("allow") == ["Bash(ls)"] and perms.get("defaultMode") == "auto"
      and len(line) == 1 and "permissions.deny +22 (secret files)" in line[0],
      "a foreign deny rule and one of ours already present: exit %r, permissions %r, line %r" % (code, perms, line))
for label, value, warn in (("null", None, "   ! permissions is not an object, left alone"),
                           ("a list", ["x"], "   ! permissions is not an object, left alone"),
                           ("a deny string", {"deny": "Read(//x)"}, "   ! permissions.deny is not a list, left alone")):
    reset_home()
    seed(hooks.USER_SETTINGS, json.dumps({"permissions": value, "theme": "dark"}))
    for run in ("first", "again"):
        code, out, _ = case("deny-bad-%s-%s" % (label.split()[-1], run), {"a": {}}, globals_=True)
        doc = json.loads(read(hooks.USER_SETTINGS))
        check(code == 1 and doc.get("permissions") == value and doc.get("theme") == "dark"
              and warn in out.splitlines() and "secret files" not in out,
              "permissions %s, %s run: exit %r, permissions %r, warning present %s"
              % (label, run, code, doc.get("permissions"), warn in out.splitlines()))
# The three ~/.hindsight/ patterns against the names that directory held when T0 measured (names only):
# every top-level file that can carry a secret matches one; the directories and the plain logs match
# none. `*` stops at a slash, as in the rule syntax T0 measured.
def hs_match(rule, name):
    body = rule[len("Read(~/.hindsight/"):-1]
    return re.fullmatch("[^/]*".join(re.escape(part) for part in body.split("*")), name) is not None
hs_rules = [r for r in DENY if r.startswith("Read(~/.hindsight/")]
for name in ("claude-code.json.disabled-20260917", "coding-agent.json", "coding-agent.json.bak", "control-plane.env",
             "control.token"):
    check(any(hs_match(r, name) for r in hs_rules), "no ~/.hindsight/ rule covers the top-level secret name %s" % name)
# profiles/ holds the Hindsight daemon's env and its .bak-* copies (names): one rule covers
# them, and the lock, log and metadata files beside them stay readable.
for name in ("profiles/coding-agent.env", "profiles/coding-agent.env.bak-pre-nvidia-20260922"):
    check(any(hs_match(r, name) for r in hs_rules), "no ~/.hindsight/ rule covers the secret name %s" % name)
for name in ("profiles/metadata.json", "profiles/coding-agent.log"):
    check(not any(hs_match(r, name) for r in hs_rules), "a ~/.hindsight/ rule covers %s, which must stay readable" % name)
for name in ("coding-agents", "coding-agents-logs", "profiles", "control.pid", "control.log", "control-plane.log"):
    check(not any(hs_match(r, name) for r in hs_rules), "a ~/.hindsight/ rule covers %s, which must stay readable" % name)

# The machine-store rules against names under a toy ~ (names only, nothing is read). `*` stops at a slash
# and `**` crosses it, as in the rule syntax. Every credential file matches one rule; the public or
# harmless neighbours (the .pub files, known_hosts, ssh config, gh's config.yml, docker's buildx directory,
# Vercel's project.json) match none.
def home_match(rule, name):
    body = rule[len("Read(~/"):-1]
    rx = "".join(".*" if t == "**" else "[^/]*" if t == "*" else re.escape(t)
                 for t in re.split(r"(\*\*|\*)", body) if t)
    return re.fullmatch(rx, name) is not None
store_rules = [r for r in DENY if r.startswith("Read(~/") and not r.startswith("Read(~/.hindsight/")
               and r != "Read(~/.claude.json*)"]
check(len(store_rules) == 14, "%d machine-store rules, expected 14: %r" % (len(store_rules), store_rules))
for name in (".npmrc", ".config/gh/hosts.yml", ".git-credentials", ".local/share/com.vercel.cli/auth.json",
             ".local/share/com.vercel.cli/sub/config.json", ".vercel/auth.json", ".supabase/access-token",
             ".aws/credentials", ".aws/config", ".kube/config", ".docker/config.json", ".ssh/id_rsa",
             ".ssh/id_ed25519", ".ssh/id_ecdsa", ".ssh/id_dsa"):
    check(any(home_match(r, name) for r in store_rules), "no machine-store rule covers the credential name ~/%s" % name)
for name in (".ssh/id_ed25519.pub", ".ssh/id_rsa.pub", ".ssh/known_hosts", ".ssh/known_hosts.old", ".ssh/config",
             ".ssh/authorized_keys", ".config/gh/config.yml", ".docker/buildx", ".docker/buildx/current",
             ".supabase/telemetry.json", ".aws/cli/cache/x.json", ".kube/cache/x", ".npmrc.example",
             ".vercel/project.json"):
    check(not any(home_match(r, name) for r in store_rules), "a machine-store rule covers ~/%s, which must stay readable" % name)

for msg in failures:
    print("FAIL", msg)
print("%d failure(s) over %d checks" % (len(failures), n_cases))
sandbox.cleanup(failures)  # a failing run keeps its toy world and prints `kept:` with its path
sys.exit(1 if failures else 0)
