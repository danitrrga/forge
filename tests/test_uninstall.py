#!/usr/bin/env python3
"""The doctor's `owned` row over every claim kind, in a world `forge sync --all --apply` built.

The world is W/forge (an engine copy plus tests/fixtures/config, one toy skill, one profile `app`), W/home
and W/projects/app (a repository with a .gitignore line and a CLAUDE.md of its own), side by side, the shape
lib.may_write allows a toy HOME to write. Codex, codex_harness, Hindsight and caveman are on, GSD is off;
systemctl is a logging stub. After the sync, by hand: a user hook in ~/.claude/settings.json, a user allow rule
and an edited env in app's settings.local.json. Nothing real is read or written, and no secret exists in it.

Assertions: PASS over a record holding .gitignore lines, a config.toml, a link and .bak files; WARN naming
settings.local.json ["env"] (never its value) after the hand edit.

Seen failing on 2af06d1 (the row read every claimed file as JSON):
  "doctor right after the sync: PASS over every claim kind -- WARN could not read: .../projects/app/.gitignore
  (.../projects/app/.gitignore unreadable (Expecting value: line 1 column 1 (char 0)))", and the hand-edit
  check with the same WARN, which named no ["env"]."""
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

print("%d checks, %d failed" % (n_checks[0], len(failures)))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
