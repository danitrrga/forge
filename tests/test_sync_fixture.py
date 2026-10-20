#!/usr/bin/env python3
"""scripts/sync/sync_agent_config.py writes ~/.claude.json, ~/.claude/settings.json,
~/.codex/hooks.json, ~/.hindsight/coding-agent.json and, in every project, settings.local.json,
.codex/ and .agents/. docs/unify-plan.md is about to cut it into forge/ components, and the gate
for every step is that nothing it prints or writes changes. This proves the generator's contract
on a sandbox and records what it did, so a refactor can be diffed against the code before it.

The sandbox is a plain-repo copy of this checkout's engine files as they are on disk (sandbox.copy_engine:
tracked or staged, so an uncommitted new file reaches it only once it is `git add`ed) beside the fixtures of
tests/fixtures/config (sandbox.seed), every profile pointed at a throwaway project, fake secrets, a toy HOME with stale and malformed
files, no network and a systemctl that only logs. On it: a dry-run writes nothing; an --apply
leaves no temp file and a second one writes nothing; --project, a session and a worktree write
only their scope; the frozen Portal gets not a byte. --dump DIR saves every run's output and
file manifest (path, type, mode, sha256); --compare DIR fails when any of them differs.

Every scope and freeze check first seeds the stale value an in-scope run would rewrite, and each
has a positive run beside it that does rewrite it, so none can pass by writing nothing anywhere.
--controls proves --compare can fail: a changed USER_HOOKS timeout and a changed indent in
forge/lib.py's write_json must each turn it red.

bin/forge session-start runs on a sandbox of its own (session_cases): every path its steps change
must be in the write log forge/lib.py keeps (lib.record), a second run logs and says nothing, and a
frozen project logs nothing beside an unfrozen run that does. Red before the log existed: "the app session start's note names the settings.local.json it wrote: note 'forge --
agent config: ~/.claude.json -> wrote | system doc: ~ app copy:AGENT-SYSTEM.md, gitignore:.gitignore,
create:CLAUDE.md, agents-md-symlink:AGENTS.md'" -- settings.local.json, .codex/config.toml and the
.agents link written and not named. Its control runs every time: with write_text's recorder call
deleted the case must fail, and does with "unlogged ['projects/app/.claude',
'projects/app/.claude/AGENT-SYSTEM.md', 'projects/app/.claude/settings.local.json', ...]". Stale links
are seeded for relink and the codex mirror to remove; with their unlinks raw again, "an app session
start removes the stale links seeded for it, and logs each: kept or unlogged
['@S@/projects/app/.agents/skills/gone']", and the same for relink's two.

Only the checkout ~/.claude/settings.json runs may write (forge/lib.py may_write), so the harness
checks that its first --apply installs the sandbox copy. With installed_root() returning None
unconditionally that check failed: "before 'None', after 'None'".

The real machine is never touched: its credentials are never copied or opened, and the
generator runs in an empty network namespace, so nothing it runs can reach a service on the host."""
import difflib
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
from sandbox import NEVER_COPY, git  # noqa: E402

GEN = os.path.join("scripts", "sync", "sync_agent_config.py")
FIXTURES = os.path.join(sandbox.FORGE, "tests", "fixtures", "config")
# The gate's fixture --dump/--compare is the proof that what the generator WRITES for this machine's real
# profiles stays byte-identical (docs/unify-plan.md, "Puntos ciegos"), so a checkout that carries the private data
# builds its world as before T7, a full copy with the real profiles. The signal is config/fixture-world.json, a data
# file of the private history (it names the profiles the cases drive); a copy without it (an engine copy) gets the
# fixture world: the engine files plus tests/fixtures/config.
WORLD = os.path.join(sandbox.FORGE, "config", "fixture-world.json")
REAL = os.path.exists(WORLD)
if REAL:
    # app, dup, memapp, other and frozen: the profiles the cases seed, drive and freeze; OLD_KEY is a `from` key of
    # config/project-relocations.json and NEW_KEY its `to`, all named by config/fixture-world.json.
    with open(WORLD, encoding="utf-8") as _f:
        _world = json.load(_f)
    APP, DUP, MEMAPP, OTHER, FROZEN = (_world[k] for k in ("app", "dup", "memapp", "other", "frozen"))
    OLD_KEY, NEW_KEY = _world["old_key"], _world["new_key"]
else:  # the `from` and `to` of tests/fixtures/config/project-relocations.json
    APP, DUP, MEMAPP, OTHER, FROZEN = "app", "dup", "memapp", "other", "frozen-app"
    OLD_KEY, NEW_KEY = "/srv/toy/old-app", "/srv/toy/new-app"
PORTAL_KEY = {"mcpServers": {"stale-portal": {"command": "stale"}}}
# (what, the file it mutates, anchor, replacement). Keyed by file because the refactor moves each
# anchor out of the generator: the indent row goes to forge/lib.py at S2, the timeout row to
# forge/hooks.py at S6.
CONTROLS = [
    ("a USER_HOOKS timeout", os.path.join("forge", "hooks.py"), 'caveman_house_rules.py" % HOOK_DIR, 5,',
     'caveman_house_rules.py" % HOOK_DIR, 7,'),
    ("the write_json indent", os.path.join("forge", "lib.py"),
     "return json.dumps(data, ensure_ascii=ensure_ascii, indent=2)",
     "return json.dumps(data, ensure_ascii=ensure_ascii, indent=3)"),
]
# lib.write_text's recorder call, which the session-start control deletes.
RECORDER = (os.path.join("forge", "lib.py"), '    record("wrote", path)\n', "")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, text, mode=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    if mode is not None:
        os.chmod(p, mode)


def read_json(p):
    return json.loads(read(p))


def write_json(p, data, mode=None):
    write(p, json.dumps(data, indent=2) + "\n", mode)


def under(rel, top):
    return rel == top or rel.startswith(top + "/")


def changed(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


class Sandbox:
    def __init__(self, mutation=None):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="forge-s0-"))
        self.forge, self.home, self.projects = (os.path.join(self.root, d) for d in ("forge", "home", "projects"))
        self.cjp = os.path.join(self.home, ".claude.json")
        self.settings = os.path.join(self.home, ".claude", "settings.json")
        self.log = os.path.join(self.root, "systemctl.log")
        self.outputs, self.manifests, self.portal_keys = {}, {}, {}
        self._copy(mutation)
        # The seeds below carry a caveman hook for --apply to repair, so the toy world runs with caveman on
        # whatever this machine's config says. Red before, once caveman is off in the real config/forge.json:
        # "FAIL  --apply repairs the seeded user-scope files: ['codex hooks.json repaired']" (that check was
        # of the mirrored row; it is now of forge's entry being taken out).
        settings = os.path.join(self.forge, "config", "forge.json")
        doc = read_json(settings)
        doc.setdefault("integrations", {})["caveman"] = True
        # The same for codex_harness: the fixture checks Codex's hook rows and .codex/config.toml. Red before,
        # with it false in the real config/forge.json: "FileNotFoundError: ... projects/<app>/.codex/config.toml".
        doc["codex_harness"] = True
        write_json(settings, doc)
        self._profiles()
        self._secrets()
        git(self.forge, "init", "-q")
        git(self.forge, "add", "-A")
        git(self.forge, "commit", "-q", "-m", "sandbox")
        self._home()

    def pp(self, name):
        return os.path.join(self.projects, name)

    def _copy(self, mutation):
        if REAL:
            sandbox.copy_checkout(self.forge)
        else:
            self._copy_fixture_world()
        if mutation:
            rel, old, new = mutation
            p = os.path.join(self.forge, rel)
            write(p, read(p).replace(old, new))  # main() checked the anchor occurs once

    def _copy_fixture_world(self):
        # The engine files plus the fixtures, for a copy that has no profiles and skills of this machine's.
        sandbox.copy_engine(self.forge)
        sandbox.seed(self.forge)
        # One toy skill, so relink has something to link and the stale links seeded for it to remove.
        write(os.path.join(self.forge, "skills", "toy-common", "SKILL.md"), "---\nname: toy-common\ndescription: stub\n---\n")

    def _profiles(self):
        self.profiles = {}
        for p in sorted(glob.glob(os.path.join(self.forge, "config", "profiles", "*.claude.json"))):
            name = os.path.basename(p)[:-len(".claude.json")]
            prof = read_json(p)
            prof["project_path"] = self.pp(name)
            if name == FROZEN:
                # No real profile is frozen since 0280905, but the freeze is still code in lib/sync, so
                # the toy world freezes its own copy of a frozen project's profile. Without this line master's
                # fixture dies at the unfrozen control with "KeyError: 'frozen'" (prof.pop("frozen")).
                prof["frozen"] = True
            write_json(p, prof)
            write(os.path.join(self.pp(name), ".claude", "skills", "x", "SKILL.md"), "---\nname: x\ndescription: stub\n---\n")
            git(self.pp(name), "init", "-q")
            if prof.get("writes_tracked_files") is False:
                # The repo owns its .gitignore (forge never edits it), and a generated file it does
                # not cover is not written: a published plugin's repo is one, so seed what it has.
                write(os.path.join(self.pp(name), ".gitignore"),
                      ".claude/settings.local.json\n.claude/AGENT-SYSTEM.md\n.codex/\n.agents/\n")
            self.profiles[name] = prof

    def _secrets(self):
        names = set()
        for rel in ("config/mcp-registry.json", "config/hindsight-coding-agents.json"):
            names |= set(re.findall(r"\$\{(\w+)\}", read(os.path.join(self.forge, rel))))
        # A profile's `env` value of the form ${NAME} is resolved from the secrets too (skills.write_settings_local).
        for p in glob.glob(os.path.join(self.forge, "config", "profiles", "*.claude.json")):
            env = read_json(p).get("env")
            names |= {m.group(1) for v in (env.values() if isinstance(env, dict) else ())
                      for m in [re.fullmatch(r"\$\{(\w+)\}", v) if isinstance(v, str) else None] if m}
        write_json(os.path.join(self.forge, "credentials", "secrets.json"), {n: "fake-" + n for n in sorted(names)}, 0o600)
        link = os.path.join(self.forge, "config", "secrets.json")
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(os.path.join("..", "credentials", "secrets.json"), link)

    def _home(self):
        h, pp = self.home, self.pp
        plugins = sorted({p for prof in self.profiles.values() for p in prof.get("plugins_keep") or []})
        write_json(self.cjp, {
            "numStartups": 3,
            "mcpServers": {"leaky": {"command": "leaky"}},  # user scope: cleared every run
            "projects": {
                OLD_KEY: {"mcpServers": {"old": {"command": "old"}}},  # relocated to NEW_KEY's old path
                pp(APP): {"allowedTools": [], "mcpServers": {"stale": {"command": "stale"}}},
                pp(DUP) + "/": {"mcpServers": {"dup": {"command": "dup"}}},
                pp(FROZEN): PORTAL_KEY,
            }}, 0o644)
        write_json(self.settings, {
            "theme": "dark",
            "enabledPlugins": dict.fromkeys(plugins + ["unkept@elsewhere"], True),
            "statusLine": {"type": "command", "command": "bash /opt/statusline.sh"},
            "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "node /opt/herdr/herdr.js"}]}],
                      "SessionStart": [{"hooks": [{"type": "command", "command": 'node "/old/claude-sessionstart-hook.js"'}]}]}})
        for s in sorted(os.listdir(os.path.join(self.forge, "skills"))):
            if os.path.isdir(os.path.join(self.forge, "skills", s)):
                os.makedirs(os.path.join(h, ".claude", "skills"), exist_ok=True)
                os.symlink(os.path.join(self.forge, "skills", s), os.path.join(h, ".claude", "skills", s))
        # The fixture's forge.json has codex_harness true: --apply repairs this file like Claude's, and the entry
        # of forge's own (the exact command) stays, written as the row says. With the switch false it would
        # take that entry out and leave the rest (tests/test_codex_harness.py).
        write_json(os.path.join(h, ".codex", "hooks.json"), {"hooks": {"Stop": "not a list", "SessionStart": [
            "junk", {"hooks": [42, {"type": "command", "command": "python3 /old/caveman_house_rules.py", "timeout": 5},
                               {"type": "command", "command": "python3 %s/hooks/caveman_house_rules.py" % self.forge,
                                "timeout": 5}]}]}})
        write(os.path.join(h, ".hindsight", "coding-agents", "dist", "claude-hook.js"), "// stub runtime; knows autoInject\n")
        write_json(os.path.join(h, ".hindsight", "coding-agents", ".install-origin.json"), {"commit": "63da8d7" + "0" * 33})
        os.makedirs(os.path.join(h, ".vscode", "extensions"))
        sandbox.stub_systemctl(os.path.join(self.root, "bin"), self.log)
        # A frozen project's stale state: an unfrozen run rewrites both, which is what makes the freeze checkable.
        write_json(os.path.join(pp(FROZEN), ".claude", "settings.local.json"),
                   {"enableAllProjectMcpServers": True, "env": {"STALE": "1"}})

    def env(self, **extra):
        return sandbox.bare_env(self.home, self.root, os.path.join(self.root, "bin"), **extra)

    def norm(self, s):
        return s.replace(self.root, "@S@")

    def run(self, step, args, checkout=None, **extra):
        checkout = checkout or self.forge
        r = subprocess.run(["unshare", "-rn", sys.executable, os.path.join(checkout, GEN)] + args, cwd=checkout,
                           env=self.env(**extra), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
        out = self.norm(r.stdout)
        self.outputs[step] = out + "exit %d\n" % r.returncode
        self.manifests[step] = self.manifest()
        self.portal_keys[step] = read_json(self.cjp)["projects"].get(self.pp(FROZEN))
        return r.returncode, out

    def manifest(self):
        """sandbox.manifest of the toy HOME, the projects and the forge copy's data/, the sandbox
        path masked so two sandboxes compare equal. The ownership record (forge/owned.py) keeps the
        SHA-256 of each value forge wrote, and a value can hold the sandbox path (a hook's command),
        which no mask reaches inside a hash: its entry is the hash of the record with every "sum"
        dropped, so the files, kinds, `at`s and owners still compare. With the raw hash, two runs of
        the same code differed only in that file (gate diff: "owned.json f 600 <hash>", both ways)."""
        m = sandbox.manifest(self.root, ("home", "projects", "forge/data"), mask=True)
        rel = os.path.join("home", ".local", "state", "forge", "owned.json")
        if rel in m and m[rel][0] == "f":
            doc = read_json(os.path.join(self.root, rel))
            for claims in doc.get("claims", {}).values():
                for c in claims:
                    c.pop("sum", None)
            body = json.dumps(doc, sort_keys=True).replace(self.root, "@S@").encode()
            m[rel] = m[rel][:2] + (hashlib.sha256(body).hexdigest(),) + m[rel][3:]
        return m

    def artifacts(self):
        """What --dump saves: every run's output and its manifest without mtimes."""
        a = {step + ".out": text for step, text in self.outputs.items()}
        for step, m in self.manifests.items():
            a[step + ".manifest"] = "".join("%s %s %s %s\n" % ((k,) + m[k][:3]) for k in sorted(m))
        return a


def cj_diff(a, b):
    """The top-level keys and project keys of two ~/.claude.json documents that differ."""
    keys = [k for k in sorted(set(a) | set(b)) if k != "projects" and a.get(k) != b.get(k)]
    pa, pb = a.get("projects", {}), b.get("projects", {})
    return keys + ["projects[%s]" % k for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)]


def exercise(sb, check):
    pp, cjp = sb.pp, sb.cjp
    tail = lambda out: sandbox.tail(out, 4)

    def seed_local(name):  # a stale env: the profile's own env replaces it
        p = os.path.join(pp(name), ".claude", "settings.local.json")
        d = read_json(p)
        d["env"] = {"STALE": "1"}
        write_json(p, d)

    def seed_key(name):
        d = read_json(cjp)
        d["projects"][pp(name)].setdefault("mcpServers", {})["stale"] = {"command": "stale"}
        write_json(cjp, d)

    def scoped(step, args, own, **extra):
        before, cj0 = sb.manifest(), read_json(cjp)
        code, out = sb.run(step, args, **extra)
        moved = changed(before, sb.manifests[step])
        stray = [p for p in moved if not under(p, "projects/" + own) and p != "home/.claude.json"]
        return code, out, moved, stray, [sb.norm(k) for k in cj_diff(cj0, read_json(cjp))]

    check("%s's profile is frozen" % FROZEN, sb.profiles[FROZEN].get("frozen") is True, "config/profiles/%s.claude.json" % FROZEN)
    m0 = sb.manifest()
    portal0 = {k: v for k, v in m0.items() if under(k, "projects/" + FROZEN)}

    # lib.may_write lets only the checkout ~/.claude/settings.json runs write. The toy HOME names
    # none until the first --apply installs the hook, which must then name the sandbox copy, or
    # every later run here would be refused and the scope checks below would pass by writing nothing.
    installed = lambda: subprocess.run([sys.executable, "-c", "from forge import lib; print(lib.installed_root())"],
                                       cwd=sb.forge, env=sb.env(), capture_output=True, text=True).stdout.strip()
    inst0 = installed()

    # The first two runs exit 1: the seeded user-scope mcpServers and the dup/ duplicate key are
    # foreign writes each repairs on a '!' line (agent_config's exit rule; both exited 0
    # before it). The run after them has nothing left to repair and exits 0.
    code, out = sb.run("dry-run", [])
    check("dry-run exits 1 (it would repair two foreign writes) and writes nothing (mtimes included)",
          code == 1 and sb.manifests["dry-run"] == m0,
          "exit %d, changed %s: %s" % (code, changed(m0, sb.manifests["dry-run"]), tail(out)))

    code, out = sb.run("apply", ["--apply"])
    m1 = sb.manifests["apply"]
    check("--apply exits 1 (it repairs two foreign writes)", code == 1, tail(out))
    inst1 = installed()
    check("installed_root() is None before the first --apply and the sandbox copy after it",
          inst0 == "None" and inst1 == sb.forge, "before %r, after %r" % (inst0, sb.norm(inst1)))
    tmp = [k for k in m1 if ".tmp" in os.path.basename(k)]
    check("--apply leaves no *.tmp* file", not tmp, tmp)
    cj = read_json(cjp)
    seeds = {"mode 600": os.stat(cjp).st_mode & 0o777 == 0o600,
             "relocated": OLD_KEY not in cj["projects"] and NEW_KEY in cj["projects"],
             "user scope cleared": not cj.get("mcpServers"),
             "duplicate key merged": pp(DUP) + "/" not in cj["projects"],
             "stale server dropped": "stale" not in cj["projects"][pp(APP)]["mcpServers"]}
    check("--apply repairs every seed in ~/.claude.json", all(seeds.values()), [k for k, v in seeds.items() if not v])
    st, cx = read_json(sb.settings), read_json(os.path.join(sb.home, ".codex", "hooks.json"))
    cmds = [h["command"] for gs in st["hooks"].values() for g in gs for h in g["hooks"]]
    seeds = {"warded": not any("claude-sessionstart-hook.js" in c for c in cmds),
             "foreign hook kept": "node /opt/herdr/herdr.js" in cmds,
             "model": st.get("model") == "sonnet",
             "codex hooks.json repaired": isinstance(cx["hooks"]["Stop"], list)
             and all(isinstance(g, dict) for g in cx["hooks"]["SessionStart"])}
    check("--apply repairs the seeded user-scope files", all(seeds.values()), [k for k, v in seeds.items() if not v])
    dirty = git(sb.forge, "status", "--porcelain")
    check("--apply writes nothing git would track in the forge copy", not dirty, dirty.strip())

    code, out = sb.run("apply-again", ["--apply"])
    wrote = [l.strip() for l in out.splitlines() if re.search(r"would write|-> wrote", l)]
    moved = changed(m1, sb.manifests["apply-again"])
    check("a second --apply writes nothing (no write lines, every mtime unchanged)", code == 0 and not wrote and not moved,
          "exit %d, lines %s, changed %s" % (code, wrote, moved))

    calls = read(sb.log).splitlines() if os.path.exists(sb.log) else []
    check("systemctl is the logging stub, called only with --user", all(c.startswith("--user ") for c in calls), calls)

    seed_local(APP)
    seed_local("forge")
    s = read_json(sb.settings)
    s["model"] = "opus"
    write_json(sb.settings, s)
    seed_key(APP)
    seed_key(OTHER)
    code, out, moved, stray, keys = scoped("project-" + APP, ["--project", APP, "--apply"], APP)
    check("--project %s writes %s and its ~/.claude.json key, nothing else" % (APP, APP),
          code == 0 and not stray and "projects/%s/.claude/settings.local.json" % APP in moved
          and keys == ["projects[@S@/projects/%s]" % APP], "exit %d, stray %s, keys %s" % (code, stray, keys))

    seed_local(MEMAPP)
    seed_key(MEMAPP)
    code, out, moved, stray, keys = scoped("session-" + MEMAPP, ["--apply"], MEMAPP, CLAUDE_PROJECT_DIR=pp(MEMAPP))
    check("a %s session writes %s and its ~/.claude.json key, no user-scope file" % (MEMAPP, MEMAPP),
          code == 0 and not stray and "home/.claude.json" in moved and keys == ["projects[@S@/projects/%s]" % MEMAPP]
          and "user-scope files: not this run's scope (project %s)" % MEMAPP in out,
          "exit %d, stray %s, keys %s" % (code, stray, keys))

    # The positive side of the two above: a forge session does repair the user scope and forge's
    # seed, both left stale by the app and memapp runs.
    code, out, moved, stray, keys = scoped("session-forge", ["--apply"], "forge", CLAUDE_PROJECT_DIR=pp("forge"))
    outside = [p for p in stray if not under(p, "home")]
    check("a forge session writes forge and the user scope (so the two checks above can fail)",
          code == 0 and not outside and "home/.claude/settings.json" in moved
          and "projects/forge/.claude/settings.local.json" in moved and "projects[@S@/projects/%s]" % OTHER not in keys,
          "exit %d, outside %s, keys %s" % (code, outside, keys))

    wt = os.path.join(sb.root, "forge-wt")
    git(sb.forge, "worktree", "add", "-q", wt)
    for d in NEVER_COPY:  # as in a real forge worktree
        os.symlink(os.path.join("..", "forge", d), os.path.join(wt, d))
    if not REAL:
        # The engine's .gitignore leaves config/forge.json untracked, so `git worktree add` does not carry
        # the seeded one over and the run stops at "! config/forge.json missing -- run bin/forge init"
        # before it reaches the worktree line. Red before, in a pure engine clone: "FAIL a worktree --apply
        # says so on its first line: ! config/forge.json missing -- run bin/forge init". A private
        # checkout tracks it, so there the worktree has it already and this does not run.
        for rel in ("config/forge.json",):
            if not os.path.exists(os.path.join(wt, rel)):
                os.makedirs(os.path.dirname(os.path.join(wt, rel)), exist_ok=True)
                shutil.copy2(os.path.join(sb.forge, rel), os.path.join(wt, rel))
    d = read_json(cjp)
    d["projects"][OLD_KEY] = {"mcpServers": {"old": {"command": "old"}}}
    write_json(cjp, d, 0o644)
    before, cj0 = sb.manifest(), read_json(cjp)
    code, out = sb.run("worktree", ["--apply"], checkout=wt)
    moved = changed(before, sb.manifests["worktree"])
    first = (out.splitlines() or [""])[0]
    check("a worktree --apply says so on its first line",
          first == "forge: @S@/forge-wt is a linked worktree -- nothing written; apply from the main checkout", first)
    # Seeded to be rewritten: the 644 mode and the key relocation. Until a fix main() chmodded
    # the file and relocated the key before looking at the scope, so this failed with
    # "it still writes ~/.claude.json -- mode 644 -> 600".
    check("a worktree --apply writes nothing", not moved, "changed %s" % moved)

    touched = [s for s, m in sb.manifests.items() if {k: v for k, v in m.items() if under(k, "projects/" + FROZEN)} != portal0
               or sb.portal_keys[s] != PORTAL_KEY or "forge/data/memory-lite/" + FROZEN in m]
    check("the frozen Portal gets not a byte, in any run (dir, ~/.claude.json key, lite store)", not touched, touched)

    p = os.path.join(sb.forge, "config", "profiles", FROZEN + ".claude.json")
    prof = read_json(p)
    prof.pop("frozen")
    write_json(p, prof)
    code, out = sb.run("unfrozen-control", ["--project", FROZEN, "--apply"])
    m = sb.manifests["unfrozen-control"]
    rewrote = ({k: v for k, v in m.items() if under(k, "projects/" + FROZEN)} != portal0
               and sb.portal_keys["unfrozen-control"] != PORTAL_KEY)
    check("control: unfrozen, a frozen project's seeds are rewritten (so the freeze check can fail)", rewrote, tail(out))

    # forge/sync.py agent_config's one exit rule, over every run above: a line whose first
    # non-space character is '!' means exit 1, and no other line does. Red on 0ad2214,
    # before the rule: "dry-run: exit 0, first '!' line \"   ! clearing user-scope (top-level)
    # mcpServers -- leak into ALL projects: ['leaky']\"", the same for apply; "worktree: exit 0, first '!' line '!! config/secrets.json is missing, so no secret
    # resolves.'"; "unfrozen-control: exit 0, first '!' line '   ! codex mcp -> @S@/projects/
    # frozen-app/.codex/config.toml NOT written !not-git-ignored(SKIPPED: repo-owned .gitignore does
    # not ignore .codex/)'".
    broken = []
    for step, text in sb.outputs.items():
        body, _, last = text.rstrip("\n").rpartition("\n")
        bang = re.search(r"(?m)^\s*!", body)
        if bool(bang) != (last != "exit 0"):
            broken.append("%s: %s, %s" % (step, last, "first '!' line %r" % body[bang.start():].lstrip("\n").splitlines()[0]
                                                    if bang else "no '!' line"))
    check("every run exits 1 exactly when it printed a '!' line", not broken, broken)


def session_start(sb, proj):
    """bin/forge session-start as the SessionStart hook runs it, for a session in project `proj`,
    with FORGE_WRITE_LOG naming a file of the test's: (exit code, the systemMessage with the sandbox
    masked, the paths logged, the manifest before, the manifest after)."""
    log = os.path.join(sb.root, "writes.log")
    write(log, "")
    # cli's own lock, not a step's write: made before the baseline, as any earlier sync made it.
    lock = os.path.join(sb.home, ".local", "state", "forge", "sync.lock")
    if not os.path.exists(lock):
        write(lock, "")
    before = sb.manifest()
    r = subprocess.run(["unshare", "-rn", sys.executable, os.path.join(sb.forge, "bin", "forge"), "session-start"],
                       cwd=sb.forge, env=sb.env(CLAUDE_PROJECT_DIR=sb.pp(proj), FORGE_WRITE_LOG=log),
                       capture_output=True, text=True, timeout=600)
    try:
        msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
    except ValueError:
        msg = "not JSON: %r %r" % (r.stdout, r.stderr)
    logged = [l.split(" ", 1)[1] for l in read(log).splitlines() if " " in l]
    return r.returncode, sb.norm(msg), logged, before, sb.manifest()


def unlogged(sb, before, after, logged):
    """The paths the manifest shows changed that the write log does not account for. A file or link
    needs its own line or a logged directory above it (a staging tree made anew); a directory is
    accounted for by a line at or under it."""
    rels = [os.path.relpath(p, sb.root) for p in logged]
    out = []
    for rel in changed_by_forge(before, after):
        is_dir = (after.get(rel) or before.get(rel))[0] == "d"
        if not any(under(rel, l) or (is_dir and under(l, rel)) for l in rels):
            out.append(rel)
    return out


def changed_by_forge(before, after):
    """changed(), less npm's own debug logs (~/.npm/_logs, from the gsd step's `npm root -g`):
    npm's writes, not forge's."""
    return [p for p in changed(before, after) if not under(p, "home/.npm")]


def gsd_installed():
    """(whether the gsd step can run here, why not): it stages the package with node."""
    try:
        base = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    ok = bool(shutil.which("node")) and os.path.isdir(os.path.join(base, "get-shit-done-cc"))
    return ok, "" if ok else "no node, or no get-shit-done-cc under `npm root -g` (%s)" % base


def session_cases(sb, check):
    """A session start tells the user about every path it wrote: each step's writes are read from
    forge/lib.py's write log, not guessed from what the step printed. A forge session (the user
    scope and every step) and a app session each run twice on a fresh sandbox: the first logs every
    path the manifest shows changed and the note names them, the second logs nothing and says
    nothing. A frozen project's session logs nothing, beside the unfrozen run that does."""
    outside = lambda logged: [p for p in logged if not p.startswith(sb.root + os.sep)]
    gsd, why = gsd_installed()
    check("the forge session start can run the gsd step (node and a global get-shit-done-cc)", gsd, why)
    # npm_nag's once-a-day stamp, as if checked just now: in the empty network namespace its
    # `npm view get-shit-done-cc version` runs to the 8 s timeout (measured 8.03 s, twice). Seeded
    # here, not in Sandbox._home, because the dumped manifests walk home/ and the stamp holds a
    # time. Measured on fresh sandboxes: the first forge session start took 15.6 s
    # unseeded and 6.5 s seeded, and its write log differed only by the stamp's own line.
    write(os.path.join(sb.home, ".cache", "forge", "gsd-stage", "NPM-CHECKED"), "%f ?\n" % time.time())
    # Links each step removes: relink's dangling mirror link and the native-memory link it severs,
    # and the codex mirror's link to a project skill that is gone.
    stale = {"forge": [(os.path.join(sb.home, ".claude", "skills", "gone"), os.path.join(sb.forge, "skills", "gone")),
                       (os.path.join(sb.home, ".claude", "projects", sb.forge.replace("/", "-"), "memory"),
                        os.path.join(sb.forge, "memories"))],
             APP: [(os.path.join(sb.pp(APP), ".agents", "skills", "gone"), os.path.join("..", "..", ".claude", "skills", "gone"))]}
    for proj in (["forge"] if gsd else []) + [APP]:
        for link, target in stale[proj]:
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(target, link)
        code, msg, logged, before, after = session_start(sb, proj)
        missing = unlogged(sb, before, after, logged)
        check("a %s session start logs every path it changes, none outside the sandbox" % proj,
              code == 0 and logged and not missing and not outside(logged),
              "exit %d, %d logged, unlogged %s, outside %s" % (code, len(logged), missing[:8], outside(logged)))
        kept = [l for l, _ in stale[proj] if os.path.lexists(l) or l not in logged]
        check("a %s session start removes the stale links seeded for it, and logs each" % proj, not kept,
              "kept or unlogged %s" % [sb.norm(l) for l in kept])
        if proj == APP:
            local = "@S@/projects/%s/.claude/settings.local.json" % APP
            check("the %s session start's note names the settings.local.json it wrote" % APP, local in msg, "note %r" % msg)
        code, msg, logged, before, after = session_start(sb, proj)
        notes = [n for n in msg[len("forge -- "):].split(" | ") if n] if msg else []
        check("a second %s session start logs nothing and says nothing" % proj,
              code == 0 and not logged and not notes and not changed_by_forge(before, after),
              "exit %d, logged %s, notes %s" % (code, logged[:8], notes))

    # Content current, mode loose: the writes the old pattern caught only by their wording
    # ("chmod 600 ~/.claude.json", "(content current, chmod 600 config.toml)") or not at all
    # ("(content current, mode corrected to 600)").
    loose = {"forge": [os.path.join(sb.home, ".hindsight", "coding-agent.json")],
             APP: [sb.cjp, os.path.join(sb.pp(APP), ".codex", "config.toml")]}
    for proj in (["forge"] if gsd else []) + [APP]:
        for p in loose[proj]:
            os.chmod(p, 0o644)
        code, msg, logged, before, after = session_start(sb, proj)
        missing = unlogged(sb, before, after, logged) + [p for p in loose[proj] if p not in logged]
        check("a %s session start that only corrects modes logs each file" % proj, code == 0 and not missing,
              "exit %d, unlogged %s, note %r" % (code, missing, msg))

    code, msg, logged, before, after = session_start(sb, FROZEN)
    check("a frozen project's session start logs nothing and writes nothing",
          code == 0 and not logged and not msg and not changed_by_forge(before, after), "logged %s, note %r" % (logged[:8], msg))
    p = os.path.join(sb.forge, "config", "profiles", FROZEN + ".claude.json")
    prof = read_json(p)
    prof.pop("frozen")
    write_json(p, prof)
    code, msg, logged, before, after = session_start(sb, FROZEN)
    portal = [l for l in logged if under(os.path.relpath(l, sb.root), "projects/" + FROZEN)]
    check("control: unfrozen, its session start logs a frozen project's paths (so the check above can fail)", portal,
          "logged %s, note %r" % (logged[:8], msg))


def recorder_control():
    """(whether the session-start case fails with lib.write_text's recorder call deleted, what it
    said): a app session start alone, on a sandbox with that one line gone."""
    rel, old, new = RECORDER
    if read(os.path.join(sandbox.FORGE, rel)).count(old) != 1:
        return None, False, "the anchor %r does not occur exactly once in %s" % (old, rel)
    sb = Sandbox(RECORDER)
    code, msg, logged, before, after = session_start(sb, APP)
    missing = unlogged(sb, before, after, logged)
    local = "@S@/projects/%s/.claude/settings.local.json" % APP
    return sb, bool(missing) or local not in msg, "unlogged %s, note %r" % (missing[:8], msg)


def compare(old, new, where):
    msgs = []
    for name in sorted(old):
        if new.get(name) == old[name]:
            continue
        diff = [l for l in difflib.unified_diff(old[name].splitlines(), new.get(name, "").splitlines(), lineterm="", n=0)
                if not l.startswith(("---", "+++", "@@"))]
        if name.endswith(".manifest"):  # a changed file shows as a -/+ pair: name the paths
            diff = list(dict.fromkeys(l[1:].split(" ")[0] for l in diff))
        msgs.append("%s differs from %s: %s%s" % (name, where, " | ".join(diff[:6]),
                                                 " (+%d more)" % (len(diff) - 6) if len(diff) > 6 else ""))
    return msgs


def load_dump(d):
    return {n: read(os.path.join(d, n)) for n in sorted(os.listdir(d))}


def main(argv):
    t0 = time.time()
    os.umask(0o022)  # file modes are in the manifest
    results = []

    def check(name, ok, detail=""):
        results.append(("PASS" if ok else "FAIL", name, "" if ok else detail))
    check.xfail = lambda name, detail: results.append(("XFAIL", name, detail))
    opt = lambda flag: argv[argv.index(flag) + 1] if flag in argv[:-1] else None

    ok, detail = sandbox.unshare_ok()
    check("the generator runs with no network: a loopback listener on the host is unreachable", ok, detail)
    # Before any sandbox exists: an exit from inside one left every sandbox built so far in /tmp,
    # with no 'sandbox kept:' line to say where.
    for what, rel, old, new in (CONTROLS if "--controls" in argv else []):
        if read(os.path.join(sandbox.FORGE, rel)).count(old) != 1:
            sys.exit("control anchor must occur exactly once in %s: %r" % (rel, old))
    sandboxes = []
    if ok:
        sb = Sandbox()
        sandboxes.append(sb)
        exercise(sb, check)
        if opt("--dump"):
            os.makedirs(opt("--dump"), exist_ok=True)
            for n, text in sb.artifacts().items():
                write(os.path.join(opt("--dump"), n), text)
        if opt("--compare"):
            msgs = compare(load_dump(opt("--compare")), sb.artifacts(), opt("--compare"))
            check("output and writes identical to %s" % opt("--compare"), not msgs, "\n      ".join(msgs))
        ss = Sandbox()
        sandboxes.append(ss)
        session_cases(ss, check)
        mut, red, detail = recorder_control()
        if mut:
            sandboxes.append(mut)
        # Passing, the message is the evidence, so it is printed too.
        results.append(("PASS" if red else "FAIL", "control: without write_text's recorder the session-start "
                        "case fails", detail if red or not mut else "it stayed green: " + detail))
        if "--controls" in argv:
            ref = sb.artifacts()
            sink = lambda *a: None
            sink.xfail = sink
            for what, rel, old, new in CONTROLS:
                mut = Sandbox((rel, old, new))
                sandboxes.append(mut)
                exercise(mut, sink)
                msgs = compare(ref, mut.artifacts(), "the clean run")
                # Passing, the messages are the evidence, so they are printed too.
                results.append(("PASS" if msgs else "FAIL", "control: %s turns --compare red" % what,
                                "\n      ".join([""] + msgs) if msgs else "--compare stayed green"))

    for level, name, detail in results:
        print("%-5s %s%s" % (level, name, (": " + str(detail)) if detail else ""))
    failures = sum(1 for r in results if r[0] == "FAIL")
    keep = "--keep" in argv or failures
    for s in sandboxes:
        if keep:
            print("sandbox kept:", s.root)
        else:
            shutil.rmtree(s.root)
    print("runtime %.1fs" % (time.time() - t0))
    print("%d failure(s) over %d cases (%d expected failure(s))"
          % (failures, len(results), sum(1 for r in results if r[0] == "XFAIL")))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
