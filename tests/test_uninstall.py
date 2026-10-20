#!/usr/bin/env python3
"""`forge uninstall` (forge/uninstall.py) and the doctor's `owned` row over every claim kind.

Each world is W/forge (an engine copy plus tests/fixtures/config, one toy skill, one profile `app`), W/home
and W/projects/app (a repository with a .gitignore line and a CLAUDE.md of its own), side by side, the shape
lib.may_write allows a toy HOME to write. Codex, codex_harness, Hindsight and caveman are on, GSD is off;
systemctl is a logging stub. `forge sync --all --apply` builds what forge writes, and then, by hand: a user
hook in ~/.claude/settings.json, a user allow rule and an edited env in app's settings.local.json; the
.gitignore line `node_modules/` and ~/.claude/settings.json.bak were there before the sync. Nothing real is
read or written, and no secret exists in the world.

Assertions:
  the doctor row: PASS over a record holding .gitignore lines, a config.toml, a link and .bak files; WARN
  naming settings.local.json ["env"] (never its value) after the hand edit;
  a dry-run changes no byte (manifest of home and projects, mtimes included) and says how much it looked at;
  `--integration hindsight` while hindsight is on and `--project app` (a live profile) are refused, exit 1,
  writing nothing; with hindsight switched off in the toy config/forge.json, `--integration hindsight --apply`
  takes out hindsight's claims only;
  `--apply`: every claim of the record is gone but the edited env, which is named on a '  ! ' line; the
  by-construction items are gone (skill links in both mirrors, the .agents link, the guard entry, the copy of
  AGENT-SYSTEM.md, the pointer block, ~/.gsd/defaults.json, ~/.cache/forge, the state dir), the claimed
  ~/.claude.json.bak too; the four hand things stay; the keys of ~/.claude.json forge never claimed are
  byte-identical; the old .bak is listed and kept; a link into another tree stays; the output names GSD's
  removal command and the command that deletes the checkout.
Negative controls, run every time, each in a world of its own:
  removable() made to ignore the digest (in the world's copy of forge/owned.py): the edited env is deleted,
  and the env check of the main world would have failed;
  owned.json removed: the claim part says NOT RUN, NOT ARMED and the by-construction count is above 0;
  a world where nothing ran: FAIL, looked at zero, exit 1.

Seen failing on 2af06d1 (this file as it is), 28 of 44 checks: "doctor right after the sync: PASS over every
claim kind -- WARN could not read: .../projects/app/.gitignore (.../projects/app/.gitignore unreadable
(Expecting value: line 1 column 1 (char 0)))" (the row read every claimed file as JSON), and every uninstall
call: "exit 2: forge: error: argument cmd: invalid choice: 'uninstall' (choose from 'sync', 'doctor', ...)".
Mutations of forge/uninstall.py, each put back from a copy, and the checks that went red: commit() writing in a
dry-run (2: "dry-run: not a byte changed", "the refusals wrote nothing"); every link in ~/.claude/skills taken
for forge's (2: "a skill link into another tree stays", and the empty world's FAIL, which then found one);
an edited claim removed like an intact one (3: the env checks)."""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOP = sandbox.mkdtemp("uninstall-test-")
os.environ["HOME"] = os.path.join(TOP, "nohome")  # before the import: nothing here may see the real HOME
sys.path.insert(0, sandbox.FORGE)
from forge import owned  # noqa: E402  (owned.current only: it reads the files a claim names)

failures, n_checks = [], [0]
USER_HOOK = "node /opt/toy/mine.js"
USER_RULE = "Bash(mine:*)"
FOREIGN = "elsewhere-skill"


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append(label)
        print("FAIL", label, "--", str(detail)[:1500])


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def commands(doc):
    """Every hook command in a settings document."""
    out = []
    for groups in (doc.get("hooks") or {}).values():
        for g in groups:
            out += [h.get("command") for h in g.get("hooks", [])]
    return out


class World:
    def __init__(self, tag, sync=True):
        self.top = os.path.join(TOP, tag)
        self.root, self.home, self.app = (os.path.join(self.top, d) for d in ("forge", "home", os.path.join("projects", "app")))
        self.tmp = os.path.join(self.top, "tmp")
        for d in (self.home, self.app, self.tmp):
            os.makedirs(d)
        sandbox.copy_engine(self.root)
        sandbox.seed(self.root)
        write(os.path.join(self.root, "skills", "toy-common", "SKILL.md"), "---\nname: toy-common\ndescription: stub\n---\n")
        cfg = load(self.cfg)
        cfg["integrations"] = {"codex": True, "gsd": False, "hindsight": True, "caveman": True}
        cfg["codex_harness"] = True
        write_json(self.cfg, cfg)
        reg = os.path.join(self.root, "config", "mcp-registry.json")
        doc = load(reg)
        doc["servers"]["hindsight-coding-agents"] = {"type": "stdio", "command": "toy-hs", "args": [], "env": {}}
        write_json(reg, doc)
        profiles = os.path.join(self.root, "config", "profiles")
        for n in os.listdir(profiles):
            os.remove(os.path.join(profiles, n))
        write_json(os.path.join(profiles, "app.claude.json"), {
            "project": "app", "project_path": self.app, "servers": ["toy-echo", "hindsight-coding-agents"],
            "env": {"TOY": "1"}, "permissions": {"allow": ["Bash(toy:*)"]}, "skills_keep": ["toy-common"],
            "plugins_keep": [], "command_guard": True})
        write_json(os.path.join(self.root, "credentials", "secrets.json"), {})
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(self.root, "config", "secrets.json"))
        sandbox.git(self.root, "init", "-q")
        sandbox.git(self.root, "add", "-A")
        sandbox.git(self.root, "commit", "-q", "-m", "world")
        write(os.path.join(self.app, ".claude", "skills", "x", "SKILL.md"), "---\nname: x\ndescription: stub\n---\n")
        write(os.path.join(self.app, ".gitignore"), "node_modules/\n")
        write(os.path.join(self.app, "CLAUDE.md"), "# app\n")
        sandbox.git(self.app, "init", "-q")
        # Things forge did not write and that must survive: ~/.claude.json's own keys, a settings.json.bak from
        # before the record, a skill link into another tree.
        write_json(self.cj, {"numStartups": 3, "projects": {"/srv/toy/elsewhere": {"allowedTools": [], "mcpServers": {"theirs": {"command": "x"}}}}})
        write_json(self.settings, {"theme": "dark"})
        write(self.settings + ".bak", "{}")
        os.makedirs(os.path.join(self.top, FOREIGN))
        os.makedirs(os.path.join(self.home, ".claude", "skills"))
        os.symlink(os.path.join(self.top, FOREIGN), os.path.join(self.home, ".claude", "skills", FOREIGN))
        write(os.path.join(self.home, ".hindsight", "coding-agents", "dist", "claude-hook.js"), "// stub runtime; knows autoInject\n")
        bin_dir = sandbox.stub_systemctl(os.path.join(self.top, "bin"), os.path.join(self.top, "systemctl.log"))
        self.env = sandbox.bare_env(self.home, self.tmp, bin_dir)
        if sync:
            # What GSD and the gsd runtime step leave, put there by hand (GSD is off in the world): a copy of the
            # defaults forge ships, byte for byte, and the staging cache.
            os.makedirs(os.path.join(self.home, ".gsd"))
            shutil.copy(os.path.join(self.root, "config", "gsd", "defaults.json"), os.path.join(self.home, ".gsd", "defaults.json"))
            write(os.path.join(self.home, ".cache", "forge", "gsd-stage", "x"), "staged\n")
            code, out = self.forge("sync", "--all", "--apply")
            check("%s: the sync builds the world" % tag, code == 0 and os.path.exists(self.registry), sandbox.tail(out, 6))

    cfg = property(lambda self: os.path.join(self.root, "config", "forge.json"))
    cj = property(lambda self: os.path.join(self.home, ".claude.json"))
    settings = property(lambda self: os.path.join(self.home, ".claude", "settings.json"))
    codex_hooks = property(lambda self: os.path.join(self.home, ".codex", "hooks.json"))
    slp = property(lambda self: os.path.join(self.app, ".claude", "settings.local.json"))
    registry = property(lambda self: os.path.join(self.home, ".local", "state", "forge", "owned.json"))

    def forge(self, *args):
        r = subprocess.run([sys.executable, os.path.join(self.root, "bin", "forge")] + list(args), cwd=self.root,
                           env=self.env, capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr

    def doctor_row(self):
        """(level, detail) of cli.owned_row, run in the world's checkout under its HOME."""
        code = ("import sys; sys.path.insert(0, %r)\nfrom forge import cli\nr = cli.owned_row()\nprint(r.level)\nprint(r.detail)"
                % self.root)
        r = subprocess.run([sys.executable, "-c", code], cwd=self.root, env=self.env, capture_output=True, text=True, timeout=120)
        lines = r.stdout.splitlines()
        return (lines[0], "\n".join(lines[1:])) if lines else ("NONE", r.stderr[-800:])

    def manifest(self):
        return sandbox.manifest(self.top, ("home", "projects"))

    def set_integration(self, name, on):
        cfg = load(self.cfg)
        cfg["integrations"][name] = on
        write_json(self.cfg, cfg)

    def hand_edits(self):
        s = load(self.settings)
        s["hooks"].setdefault("UserPromptSubmit", []).append({"hooks": [{"type": "command", "command": USER_HOOK}]})
        write_json(self.settings, s)
        sl = load(self.slp)
        sl["permissions"]["allow"].append(USER_RULE)
        sl["env"]["TOY"] = "9"
        write_json(self.slp, sl)


def looked(out):
    """(claims, by-construction items) from the line every run prints, or None."""
    m = re.search(r"looked at (\d+) claim\(s\) and (\d+) item\(s\)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def claims_left(world, before):
    """The claims of `before` (the registry's {file: [claim]}) still found in their file, as (file, at)."""
    out = []
    for f, cs in before.items():
        for c in cs:
            try:
                found, _ = owned.current(f, c)
            except Exception as e:  # an unreadable file: the claim is not known to be gone
                found = repr(e)
            if found:
                out.append((f.replace(world.top, "W"), json.dumps(c["at"])))
    return out


# ---------------------------------------------------------------- the main world
w = World("main")
level, detail = w.doctor_row()
check("doctor right after the sync: PASS over every claim kind -- %s %s" % (level, detail),
      level == "PASS" and re.search(r"\d+ claim\(s\) in \d+ file\(s\)", detail), detail)
kinds = {c["kind"] for cs in load(w.registry)["claims"].values() for c in cs}
lines = [f for f, cs in load(w.registry)["claims"].items() if any(c["at"][:1] == ["line"] for c in cs)]
check("control: the record holds .gitignore lines and file claims -- kinds %s, line files %s" % (sorted(kinds), lines),
      "file" in kinds and any(f.endswith(".gitignore") for f in lines))

w.hand_edits()
level, detail = w.doctor_row()
check("doctor after a hand edit of a claimed key: WARN naming the file and [\"env\"] -- %s %s" % (level, detail),
      level == "WARN" and "settings.local.json" in detail and '["env"]' in detail, detail)
check("the WARN names no value", '"9"' not in detail and "TOY" not in detail, detail)

# A dry-run writes nothing at all.
before = w.manifest()
code, out = w.forge("uninstall")
check("dry-run: exit 0 -- exit %d: %s" % (code, sandbox.tail(out, 4)), code == 0, out)
diff = sorted(k for k in set(before) | set(w.manifest()) if before.get(k) != w.manifest().get(k))
check("dry-run: not a byte changed -- %s" % diff[:8], not diff)
seen = looked(out)
check("dry-run: says how many claims and by-construction items it looked at -- %r" % (seen,),
      seen is not None and seen[0] > 0 and seen[1] > 0, out)

# Refusals.
code, out = w.forge("uninstall", "--integration", "hindsight", "--apply")
check("--integration hindsight while on: refused, exit 1 -- exit %d: %s" % (code, sandbox.tail(out, 2)),
      code == 1 and "! hindsight is on in config/forge.json: set it false first" in out, out)
code, out = w.forge("uninstall", "--project", "app", "--apply")
check("--project of a live profile: refused, exit 1 -- exit %d: %s" % (code, sandbox.tail(out, 2)), code == 1 and "!" in out, out)
diff = sorted(k for k in set(before) | set(w.manifest()) if before.get(k) != w.manifest().get(k))
check("the refusals wrote nothing -- %s" % diff[:8], not diff)

# --integration hindsight once it is off: hindsight's claims only.
reg = load(w.registry)["claims"]
mine = {f: [c for c in cs if c["owner"] == "hindsight"] for f, cs in reg.items()}
mine = {f: cs for f, cs in mine.items() if cs}
rest = {f: [c for c in cs if c["owner"] != "hindsight" and c.get("part") != "bak"] for f, cs in reg.items()}
w.set_integration("hindsight", False)
code, out = w.forge("uninstall", "--integration", "hindsight", "--apply")
check("--integration hindsight, off: exit 0 -- exit %d: %s" % (code, sandbox.tail(out, 4)), code == 0, out)
check("control: hindsight has claims in three files at least -- %s" % sorted(mine), len(mine) >= 3)
check("--integration hindsight: every hindsight claim is gone -- %s" % claims_left(w, mine)[:6], not claims_left(w, mine))
left = claims_left(w, rest)
check("--integration hindsight: every other claim stays -- %d of %d"
      % (len(left), sum(len(v) for v in rest.values())), len(left) == sum(len(v) for v in rest.values()), left)
check("--integration hindsight: its claims leave the record, the others stay",
      not any(c["owner"] == "hindsight" for cs in load(w.registry)["claims"].values() for c in cs)
      and any(c["owner"] == "caveman" for cs in load(w.registry)["claims"].values() for c in cs))
w.set_integration("hindsight", True)

# The whole uninstall.
reg = load(w.registry)["claims"]
cj_before = load(w.cj)
check("control: the SessionStart row and the claimed ~/.claude.json.bak are there",
      any("bin/forge session-start" in c for c in commands(load(w.settings))) and os.path.exists(w.cj + ".bak"))
code, out = w.forge("uninstall", "--apply")
check("apply: exit 0 -- exit %d: %s" % (code, sandbox.tail(out, 6)), code == 0, out)
left = claims_left(w, reg)
check("apply: every claim is gone but the edited env -- %s" % left, left == [("W/projects/app/.claude/settings.local.json", '["env"]')], out)
check("apply: the edited env is named on a '  ! ' line", any(l.startswith("  ! ") and "settings.local.json" in l and '["env"]' in l
                                                           for l in out.splitlines()), out)
sl = load(w.slp) if os.path.exists(w.slp) else {}
check("apply: the edited env stays as the user left it -- %r" % sl.get("env"), sl.get("env") == {"TOY": "9"})
check("apply: the user's allow rule stays, forge's goes -- %r" % sl.get("permissions"),
      sl.get("permissions") == {"allow": [USER_RULE]})
check("apply: the guard entry and the Hindsight rows are out of settings.local.json -- %r" % sl.get("hooks"), "hooks" not in sl)
s = load(w.settings)
check("apply: the user's hook stays, every forge row goes, the SessionStart row too -- %r" % commands(s), commands(s) == [USER_HOOK])
check("apply: settings.json keeps its own keys, forge's go -- %r" % sorted(s), sorted(s) == ["hooks", "theme"])
check("apply: ~/.codex/hooks.json, left {}, is deleted", not os.path.exists(w.codex_hooks))
check("apply: the old settings.json.bak stays", read(w.settings + ".bak") == "{}")
check("apply: the old .bak is listed with its path", "~/.claude/settings.json.bak" in out, out)
check("apply: the claimed ~/.claude.json.bak is deleted", not os.path.exists(w.cj + ".bak"))
cj = load(w.cj)
check("apply: ~/.claude.json keys forge never claimed are byte-identical",
      json.dumps(cj.get("numStartups")) == json.dumps(cj_before.get("numStartups"))
      and json.dumps(cj["projects"].get("/srv/toy/elsewhere")) == json.dumps(cj_before["projects"]["/srv/toy/elsewhere"])
      and sorted(cj) == sorted(cj_before), cj)
check("apply: the .gitignore keeps the line that predates forge, alone", read(os.path.join(w.app, ".gitignore")) == "node_modules/\n",
      read(os.path.join(w.app, ".gitignore")))
check("apply: CLAUDE.md is what it was before the pointer", read(os.path.join(w.app, "CLAUDE.md")) == "# app\n",
      read(os.path.join(w.app, "CLAUDE.md")))
gone = {"~/.claude/skills/toy-common": os.path.join(w.home, ".claude", "skills", "toy-common"),
        "~/.codex/skills/toy-common": os.path.join(w.home, ".codex", "skills", "toy-common"),
        "app/.agents/skills/x": os.path.join(w.app, ".agents", "skills", "x"),
        "app/AGENTS.md": os.path.join(w.app, "AGENTS.md"),
        "app/.claude/AGENT-SYSTEM.md": os.path.join(w.app, ".claude", "AGENT-SYSTEM.md"),
        "app/.codex/config.toml": os.path.join(w.app, ".codex", "config.toml"),
        "~/.hindsight/coding-agent.json": os.path.join(w.home, ".hindsight", "coding-agent.json"),
        "~/.gsd/defaults.json": os.path.join(w.home, ".gsd", "defaults.json"),
        "~/.cache/forge": os.path.join(w.home, ".cache", "forge"),
        "~/.local/state/forge": os.path.join(w.home, ".local", "state", "forge")}
check("apply: every by-construction item is gone -- left %s" % [k for k, p in gone.items() if os.path.lexists(p)],
      not any(os.path.lexists(p) for p in gone.values()))
check("apply: a skill link into another tree stays", os.path.islink(os.path.join(w.home, ".claude", "skills", FOREIGN)))
check("apply: the target of forge's skill links stays", os.path.isfile(os.path.join(w.root, "skills", "toy-common", "SKILL.md")))
check("apply: the output names GSD's removal command", "get-shit-done-cc" in out and "--uninstall" in out, out)
check("apply: the output ends with the command that deletes the checkout, never run",
      "rm -rf %s" % w.root in out.strip().splitlines()[-1] and os.path.isdir(w.root), sandbox.tail(out, 2))

# ---------------------------------------------------------------- negative controls
# removable() ignoring the digest: the edited env goes, which the main world's check catches.
m = World("mutant")
m.hand_edits()
src = os.path.join(m.root, "forge", "owned.py")
text = read(src)
anchor = '    return digest(current_value) == c["sum"]\n'
check("control: the removable() anchor occurs once", text.count(anchor) == 1)
write(src, text.replace(anchor, "    return True\n"))
code, out = m.forge("uninstall", "--apply")
sl = load(m.slp) if os.path.exists(m.slp) else {}
check("control: removable() ignoring the digest deletes the edited env (red for the main world) -- env %r" % sl.get("env"),
      "env" not in sl, out)

# No record: the claim part is NOT RUN, NOT ARMED, the by-construction part still runs and counts.
n = World("norecord")
os.remove(n.registry)
code, out = n.forge("uninstall")
seen = looked(out)
check("no record: the claim part says NOT RUN, NOT ARMED -- %s" % sandbox.tail(out, 4), "NOT RUN, NOT ARMED" in out, out)
check("no record: the by-construction count is above 0, exit 0 -- exit %d, %r" % (code, seen),
      code == 0 and seen is not None and seen[1] > 0, out)

# Nothing ran: looked at zero is a FAIL.
e = World("empty", sync=False)
code, out = e.forge("uninstall")
check("an empty world: FAIL, looked at zero, exit 1 -- exit %d: %s" % (code, sandbox.tail(out, 3)),
      code == 1 and "FAIL" in out and "looked at zero" in out, out)

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
