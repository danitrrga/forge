#!/usr/bin/env python3
"""`forge list` (every project, one project) and `forge config` by flags (forge/configure.py, forge/render.py's cards).

The world is a toy (tests/sandbox.py): an engine copy, a toy HOME with the skills toy-common, toy-a .. toy-e, and these projects:
`multi` (an extras row `@TOYSET`, `toy-c`; two profiles), `plain` (no extras row: its own skills_keep, a server, two options),
`profiled` (an extras row holding `toy-c`, and the profile `x`, whose row holds `toy-c` too), `bare` (no skills_keep: every global
skill) and `frozen-p`. The skill tables are applied once (sync_skill_keep.py, then forge sync --apply --all) so the world is
consistent before a case starts. Every command runs the copy's bin/forge with only the toy HOME's environment.

Cases (the plan's control list of 4.4 U3b; (h), the screen, belongs to the second half):
  a  `forge list` and `forge list NAME`: the readable view and --json say the same, key by key.
  b  a common skill goes off through skill_keep.common_opt_out (forge.json), never by editing the project's skills_keep: the
     project file follows (sync_skill_keep.py), `--check` stays 0 and a later apply does not bring the skill back; a skill in an
     extras row is removed from that row; a skill of a project with no row is removed from its own list.
  c  an unknown project, skill, server, set, option, type or profile is exit 2 naming the closest one and the list.
  d  no escape code into a pipe or with NO_COLOR; a terminal gets them (a pty).
  e  off and on again leaves the generated settings.local.json with the same hash (and forge.json byte for byte).
  f  the write rule: no terminal and no flag is a dry-run that changes no file; `--apply` and `--yes` write once; in a pty `n`,
     a bare Enter and the input ending write nothing and `y` writes; a file changed while the owner decided is refused.
  g  a skill that arrives through a set is refused (exit 2) with the tree intact and the two commands printed; each of them, run
     in a clean world, does what it says; a call with several flags in which one is refused writes none of them.
  i  `forge config P @x --off skill:s` changes the profile's row and not the project's extras row.
  k  every printed undo, run as printed, restores the files; l  a server with a missing secret is refused; m  the last skills are
     not taken out; n  a file unreadable at the write is a one-line error; o  the rollback of the first file; differing  its own control.
  j  the rest of the refusals (a project that keeps every skill, a frozen project, a flag given on and off, a malformed TYPE:NAME,
     no flag and no terminal), `forge list @` and `@NAME` as they were, and that no read changes a file.

Written first, run against master (3ecfca4), which has no `config` and no `forge list` without @: 83 FAIL, among them
"a: forge list lists the projects -- exit 2, stderr 'forge list: no argument; it takes @ (this project's profiles) or @NAME (one
profile)'" and "b: forge config plain --off skill:toy-common --apply exits 0 -- exit 2, stderr 'usage: forge [-h] ... forge:
error: argument cmd: invalid choice: 'config'...". Case j's pinned `forge list @` text was taken from master before the change.
Negative controls, each a mutation made by hand in the engine, run once and not kept (the first message each produced):
  a  the readable card leaving out its last server -> "FAIL a: list, multi: the readable card and --json say the same -- human and
     json differ: servers"
  b  skill_off writing a common skill into the project's own list (and the two checks that would catch it taken out) -> "FAIL b:
     skills_keep edited by hand: a later sync_skill_keep.py --apply brings the skill back -- skills_keep edited by hand -- ['toy-d',
     'toy-common']"
  c  need() raising with no suggestion -> "FAIL c: config plain --off skill:toy-comon names the closest skill -- no suggestion in:
     forge config: no skill 'toy-comon'"
  d  render.color_on() always true -> "FAIL d: no escape code into a pipe -- escape codes in piped output: '\x1b[1mbare\x1b[0m ..."
  e  skill_on doing nothing (and the verify step out) -> "FAIL e: a common skill: settings.local.json is the same after the undo --
     settings.local.json differs after undo"
  f  the write decision `go = yes` made `go = True` -> "FAIL f: and the world did not change -- dry-run wrote: ['forge/config', ...]" and
     "FAIL f: in a terminal, n writes nothing -- wrote without asking: [...]"
  f  the staleness check of commit() out -> "FAIL f: a file changed while the owner decided is refused, exit 1, and not written over";
     the form check out -> "FAIL f: a project file in another form is refused (exit 1) and not rewritten -- (0, ..."
  g  plan() writing what it had applied before it re-raises a Refusal -> "FAIL g: a call with several flags in which one is refused
     writes none -- wrote despite refusal: exit 2; ['forge/config', 'forge/config/forge.json']" (the first try passed: the refused
     flag was applied before any accepted one, so there was nothing to write; the case now puts toy-c before toy-a)
  i  cmd_config ignoring the @PROFILE -> "FAIL i: the project's extras row did not change -- profile change leaked to the project:
     {'multi.claude.json': ['@TOYSET', 'toy-c'], 'profiled.claude.json': ['toy-d']}"
Round of fixes after the review of the pull request (each assertion seen failing against 798896c, the merge of master into 84b5b22; 15 FAIL):
  k  every undo the command prints is RUN in the world and every file compared with before: "FAIL k: a set off and a skill of it on (the
     review's input): the printed undo `forge config multi --on set:TOYSET --off skill:toy-b` runs -- exit 2: forge config: skill
     'toy-b' of project 'multi' is kept after the change although it was asked off"; "FAIL k: a set off: after the undo every file is
     what it was -- differ: ['forge.json']" (the set came back at the end of its row: `--on set:` now puts it after the sets there).
     The project file's `skills_keep` is compared sorted: sync_skill_keep.py puts a common skill that comes back at the end.
  l  `--on server:X` with a missing secret: "FAIL l: ... is exit 2 and writes nothing -- exit 1, wrote: [...'plain.claude.json'...];
     forge config: written, but forge sync plain --apply exits 1"
  m  the last skills: "FAIL m: an extras row: taking out every skill is exit 2 and writes nothing -- exit 0, wrote: [...]"
  n  a file unreadable at the write: a traceback ending in `lib.Unreadable ... Permission denied: '@S@/forge/config/forge.json'`
  o  the rollback of the first file (config/projects read-only, `--off set:TOYSET --on server:toy-two`): it passed at once, so its
     control is the rollback loop of _write taken out by hand: "FAIL o: both files are byte for byte as before -- differ: ['forge.json']"
  differing  a card that lost its project name: "FAIL differing: a card that lost its project name is told apart" (the old check
     was "the name appears in the title", and the path contains the name).
"""
import hashlib
import json
import os
import pty
import re
import select
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures = []
SKILLS = ("toy-common", "toy-a", "toy-b", "toy-c", "toy-d", "toy-e")
SETS = {"TOYSET": ["toy-a", "toy-b"], "SOLO": ["toy-e"]}
EXTRAS = {"multi.claude.json": ["@TOYSET", "toy-c"], "profiled.claude.json": ["toy-c", "toy-d"]}
REGISTRY = {"toy-echo": {"type": "stdio", "command": "toy-echo", "args": [], "env": {}},
            "toy-two": {"type": "stdio", "command": "toy-two", "args": [], "env": {}}}
DEFS = {"toy-b": {"description": "toy B", "color": "red", "skills": ["@TOYSET"], "plugins": ["p-def@m"], "server_kinds": ["analytics"],
                  "permissions": {"allow": ["Read"]}, "env": {"TOY_B": "1"}},
        "list": {"description": "named like the command", "color": "blue", "skills": ["toy-a"]},
        "x": {"description": "toy x", "color": "green", "skills": ["toy-a"]}}
PROJECTS = {
    "multi": {"skills_keep": [], "plugins_keep": ["p-def@m"], "servers": ["toy-echo"], "ui": True, "enableAllProjectMcpServers": True,
              "profiles": {"default": "code", "offered": {
                  "toy-b": {"skills": ["toy-c"], "plugins": ["toy-plugin@x"], "servers": {"analytics": "toy-echo"}}, "list": {}}}},
    "plain": {"skills_keep": ["toy-common", "toy-d"], "servers": ["toy-echo"], "ui": True, "command_guard": False},
    "profiled": {"skills_keep": [], "profiles": {"default": "code", "offered": {"x": {"skills": ["toy-c"]}}}},
    "bare": {},
    "frozen-p": {"frozen": True, "skills_keep": ["toy-common"]},
}


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_text(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


class World:
    """An engine copy, a toy HOME and the five projects above; `mutate` is one text replacement (file, old, new) in the copy."""

    def __init__(self, mutate=None):
        self.root = sandbox.mkdtemp("forge-conf-")
        self.forge, self.home = os.path.join(self.root, "forge"), os.path.join(self.root, "home")
        sandbox.copy_engine(self.forge)
        sandbox.seed(self.forge)
        if mutate:
            rel, old, new = mutate
            p = os.path.join(self.forge, rel)
            text = read_text(p)
            assert text.count(old) == 1, "the control's anchor is not in %s" % rel
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
        for s in SKILLS:
            os.makedirs(os.path.join(self.home, ".claude", "skills", s))
        cfg = os.path.join(self.forge, "config")
        doc = read_json(os.path.join(cfg, "forge.json"))
        doc["integrations"] = {}
        doc.pop("codex_harness", None)
        doc["skill_keep"]["sets"] = SETS
        doc["skill_keep"]["extras"] = EXTRAS
        write_json(os.path.join(cfg, "forge.json"), doc)
        write_json(os.path.join(cfg, "mcp-registry.json"), {"servers": REGISTRY})
        for f in os.listdir(os.path.join(cfg, "projects")):
            os.remove(os.path.join(cfg, "projects", f))
        for name, body in PROJECTS.items():
            write_json(os.path.join(cfg, "projects", name + ".claude.json"), dict(body, project=name, project_path=self.pp(name)))
            os.makedirs(self.pp(name))
            sandbox.git(self.pp(name), "init", "-q")
        for name, d in DEFS.items():
            write_json(os.path.join(cfg, "profile-defs", name + ".json"), d)
        os.makedirs(os.path.join(self.forge, "credentials"))
        write_json(os.path.join(self.forge, "credentials", "secrets.json"), {})
        os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))
        sandbox.git(self.forge, "init", "-q")
        sandbox.git(self.forge, "add", "-A")
        sandbox.git(self.forge, "commit", "-q", "-m", "sandbox")
        r = self.script("sync_skill_keep.py", "--apply")
        assert r.returncode == 0, "the world's skill tables did not apply: %s%s" % (r.stdout, r.stderr)
        code, out, err = self.forge_cmd(["sync", "--apply", "--all"])
        assert code == 0, "the world's first sync failed: %s%s" % (out, err)

    def pp(self, name):
        return os.path.join(self.root, "projects", name)

    def env(self, **extra):
        # The toy HOME's own mise and xdg dirs (ORDERS 21), and nothing of the real environment.
        return sandbox.bare_env(self.home, self.root, MISE_DATA_DIR=os.path.join(self.home, ".local", "share", "mise"),
                                MISE_SYSTEM_CONFIG_DIR=os.path.join(self.home, ".config", "mise-system"), **extra)

    def script(self, name, *args):
        return subprocess.run([sys.executable, os.path.join(self.forge, "scripts", "sync", name)] + list(args), cwd=self.forge,
                              env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)

    def forge_cmd(self, args, cwd=None, **env):
        """(exit code, stdout, stderr) of bin/forge `args`, the world's root written @S@."""
        r = subprocess.run([sys.executable, os.path.join(self.forge, "bin", "forge")] + list(args), cwd=cwd or self.forge,
                           env=self.env(**env), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode, r.stdout.replace(self.root, "@S@"), r.stderr.replace(self.root, "@S@")

    def pty_cmd(self, args, answers=(), cwd=None, during=None, **env):
        """(exit code, everything the terminal showed) of bin/forge `args` with a pty as stdin, stdout and stderr. Each of `answers`
        (bytes) is sent when the next prompt `[y/N]` shows; `during` is called once, just before the first answer is sent."""
        master, slave = pty.openpty()
        p = subprocess.Popen([sys.executable, os.path.join(self.forge, "bin", "forge")] + list(args), cwd=cwd or self.forge,
                             env=self.env(**env), stdin=slave, stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
        os.close(slave)
        seen, pending, deadline = b"", list(answers), time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.2)[0]:
                    try:
                        got = os.read(master, 4096)
                    except OSError:  # EIO: the other end closed
                        break
                    if not got:
                        break
                    seen += got
                    if pending and seen.count(b"[y/N]") > len(answers) - len(pending):
                        if during and len(pending) == len(answers):
                            during()
                        os.write(master, pending.pop(0))
                elif p.poll() is not None:
                    break
            else:
                p.kill()
            try:
                code = p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                code = p.wait()
        finally:
            os.close(master)
        return code, seen.decode("utf-8", "replace").replace(self.root, "@S@")

    def doc(self):
        return read_json(os.path.join(self.forge, "config", "forge.json"))

    def proj(self, name):
        return read_json(os.path.join(self.forge, "config", "projects", name + ".claude.json"))

    def forge_text(self):
        return read_text(os.path.join(self.forge, "config", "forge.json"))

    def settings_hash(self, name):
        with open(os.path.join(self.pp(name), ".claude", "settings.local.json"), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def tree(self):
        return sandbox.manifest(self.root)


def changed(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


# ---- the two views ---------------------------------------------------------------------------------------------------------

def parse_card(text):
    """{label: value text} of a card's labelled lines, and the title line under the key `title`."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^  ([a-z-]+)\s{2,}(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
        elif line and not line.startswith(" ") and "title" not in out:
            out["title"] = line
    return out


def items(text):
    return set() if text in ("none", "") else set(text.split(", "))


def differing(js, human):
    """The keys of one card (JSON) whose value the readable text does not say; [] when they say the same."""
    h, bad = parse_card(human), []
    for key, val in js.items():
        label = key.replace("_", "-")
        txt = h.get(label, "")
        if key == "project":
            ok = h.get("title", "").split("  ")[0] == val
        elif key == "path":
            ok = h.get("title", "").split("  ")[1:2] == [val]
        elif key == "frozen":
            ok = ("frozen" in h.get("title", "")) == val
        elif key == "origins":
            ok = True  # said inside the skills line
        elif key == "skills" and isinstance(val, int):
            ok = txt.split()[:1] == [str(val)]
        elif key == "skills":
            ok = {i.split(" (")[0] for i in items(txt)} == set(val) or (val == ["*"] and txt.startswith("*"))
            for name, origin in (js.get("origins") or {}).items():
                ok = ok and ("%s (%s)" % (name, ",".join(origin))) in txt
        elif key == "profiles":
            ok = (txt == "none") if val is None else items(txt) == {val["default"] + " (default)"} | set(val["offered"])
        elif key == "options":
            ok = all(("%s %s" % (k, {True: "on", False: "off", None: "unset"}[v])) in txt for k, v in val.items())
        elif isinstance(val, list):
            ok = {i.split(" (")[0] for i in items(txt)} == set(val)
        else:
            ok = False
        if not ok:
            bad.append(key)
    return bad


def case_differing():
    """differing() must tell a card that lost its project name, or its path, from one that has them."""
    js = {"project": "multi", "path": "/srv/projects/multi", "frozen": False}
    good = "multi  /srv/projects/multi"
    check("differing: a card that has its name and path is the same", differing(js, good) == [], differing(js, good))
    for label, human in (("its project name", "/srv/projects/multi"), ("its path", "multi  /srv/other"), ("both", "")):
        bad = differing(js, human)
        # Control: the old check ("the name appears in the title") passed all three of these; it fails with `a card that lost ...`.
        check("differing: a card that lost %s is told apart" % label, bad != [], "a card that lost %s says the same as the JSON" % label)


def case_a(w):
    code, out, err = w.forge_cmd(["list"])
    check("a: forge list lists the projects", code == 0 and all(n in out for n in PROJECTS), "exit %d, stdout %r, stderr %r" % (code, out, err))
    code, js_out, err = w.forge_cmd(["list", "--json"])
    cards = json.loads(js_out) if code == 0 else None
    check("a: forge list --json is one short card per project, by name", cards is not None and [c["project"] for c in cards] == sorted(PROJECTS),
          (code, js_out, err))
    code, names, err = w.forge_cmd(["list", "--names"])
    check("a: forge list --names is the names, one per line", code == 0 and names.split("\n") == sorted(PROJECTS) + [""], (code, names, err))
    if cards:
        blocks = out.strip("\n").split("\n\n")
        check("a: one block per project in the readable list", len(blocks) == len(cards), "%d blocks for %d cards" % (len(blocks), len(cards)))
        for card, block in zip(cards, blocks):
            # Control: a view that leaves a server out of one of the two (the readable one) fails with `human and json differ: servers`.
            bad = differing(card, block)
            check("a: list, %s: the readable card and --json say the same" % card["project"], not bad, "human and json differ: %s" % ", ".join(bad))
        by = {c["project"]: c for c in cards}
        check("a: the short card says what it must", by["plain"]["servers"] == ["toy-echo"] and by["plain"]["skills"] == 2
              and by["plain"]["options"] == {"ui": True, "command_guard": False, "enableAllProjectMcpServers": None}
              and by["multi"]["profiles"] == {"default": "code", "offered": ["toy-b", "list"]} and by["bare"]["profiles"] is None
              and by["frozen-p"]["frozen"] is True and by["bare"]["skills"] == "*", by)
    for name in PROJECTS:
        code, out, err = w.forge_cmd(["list", name])
        code2, js_out, err2 = w.forge_cmd(["list", name, "--json"])
        card = json.loads(js_out) if code2 == 0 else None
        check("a: forge list %s exits 0 in both forms" % name, code == 0 and code2 == 0 and card is not None, (code, err, code2, err2))
        if card:
            bad = differing(card, out)
            check("a: list %s, the readable card and --json say the same" % name, not bad, "human and json differ: %s" % ", ".join(bad))
            check("a: the full card of %s names where each skill comes from" % name,
                  isinstance(card["skills"], list) and ("origins" in card) == (name != "bare"), card)
    code, js_out, err = w.forge_cmd(["list", "multi", "--json"])
    card = json.loads(js_out)
    check("a: multi's skills and where they come from",
          card["origins"] == {"toy-a": ["set:TOYSET"], "toy-b": ["set:TOYSET"], "toy-c": ["extras"], "toy-common": ["common"]}
          and sorted(card["skills"]) == ["toy-a", "toy-b", "toy-c", "toy-common"], card)
    check("a: and its sets", card["sets"] == ["TOYSET"], card)
    code, js_out, err = w.forge_cmd(["list", "plain", "--json"])
    card = json.loads(js_out)
    check("a: plain's skills: the common one and its own", card["origins"] == {"toy-common": ["common", "project"], "toy-d": ["project"]}, card)


# ---- b: the layer that owns the data ---------------------------------------------------------------------------------------

def case_b():
    w = World()
    row0 = w.doc()["skill_keep"]["extras"]["multi.claude.json"]
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-common", "--apply"])
    check("b: forge config plain --off skill:toy-common --apply exits 0", code == 0, "exit %d, stderr %r, stdout %r" % (code, err, out))
    doc = w.doc()
    check("b: the opt-out is in forge.json", doc["skill_keep"]["common_opt_out"].get("plain.claude.json") == ["toy-common"],
          doc["skill_keep"]["common_opt_out"])
    check("b: the project file follows", "toy-common" not in w.proj("plain")["skills_keep"] and "toy-d" in w.proj("plain")["skills_keep"],
          w.proj("plain")["skills_keep"])
    check("b: it said which layer it touched and the command that undoes it", "common_opt_out" in out and "forge config plain --on skill:toy-common" in out, out)
    # Control: a version that edits the project file's skills_keep by hand (and not common_opt_out) fails with `skills_keep edited by hand`:
    # sync_skill_keep.py puts the common skill back.
    after = w.script("sync_skill_keep.py", "--apply")
    check("b: skills_keep edited by hand: a later sync_skill_keep.py --apply brings the skill back",
          "toy-common" not in w.proj("plain")["skills_keep"] and "0 project(s) updated" in after.stdout,
          "skills_keep edited by hand -- %s" % w.proj("plain")["skills_keep"])
    check("b: sync_skill_keep.py --check is 0 after it", w.script("sync_skill_keep.py", "--check").returncode == 0, "--check is not 0")
    # A skill in an extras row: removed from the row (not opted out); a project with no row: its own list.
    code, out, err = w.forge_cmd(["config", "multi", "--off", "skill:toy-c", "--apply"])
    doc = w.doc()
    check("b: a skill of an extras row is removed from the row", code == 0 and doc["skill_keep"]["extras"]["multi.claude.json"] == ["@TOYSET"]
          and "multi.claude.json" not in doc["skill_keep"]["common_opt_out"] and "toy-c" not in w.proj("multi")["skills_keep"],
          (code, err, doc["skill_keep"]["extras"]["multi.claude.json"], w.proj("multi")["skills_keep"]))
    w.forge_cmd(["config", "plain", "--on", "skill:toy-common", "--apply"])  # (toy-d is now the project's last skill: case m)
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-d", "--apply"])
    check("b: a skill of a project with no row is removed from its own list", code == 0 and "toy-d" not in w.proj("plain")["skills_keep"],
          (code, err, w.proj("plain")["skills_keep"]))
    check("b: and forge.json did not take it", "toy-d" not in json.dumps(w.doc()["skill_keep"]["common_opt_out"]), w.doc()["skill_keep"]["common_opt_out"])
    code, out, err = w.forge_cmd(["config", "multi", "--on", "skill:toy-c", "--apply"])
    check("b: --on puts a skill back where it came from", code == 0 and w.doc()["skill_keep"]["extras"]["multi.claude.json"] == row0[:1] + ["toy-c"],
          (code, err, w.doc()["skill_keep"]["extras"]["multi.claude.json"]))
    return w


# ---- c: names that do not exist --------------------------------------------------------------------------------------------

def case_c(w):
    cases = (
        (["list", "mult"], "project", "multi"),
        (["config", "mult", "--off", "skill:toy-a"], "project", "multi"),
        (["config", "plain", "--off", "skill:toy-comon"], "skill", "toy-common"),
        (["config", "plain", "--on", "skill:toy-dd"], "skill", "toy-d"),
        (["config", "plain", "--on", "server:toy-ech"], "server", "toy-echo"),
        (["config", "plain", "--off", "server:toy-tw"], "server", "toy-two"),
        (["config", "multi", "--off", "set:TOYSE"], "set", "TOYSET"),
        (["config", "plain", "--off", "option:ui2"], "option", "ui"),
        (["config", "plain", "--off", "skil:toy-a"], "type", "skill"),
        (["config", "profiled", "@xx", "--off", "skill:toy-c"], "profile", "@x"),
    )
    for args, kind, near in cases:
        code, out, err = w.forge_cmd(args)
        # Control: a message with no suggestion fails with `no suggestion in: <message>`.
        check("c: %s is exit 2" % " ".join(args), code == 2 and out == "", "exit %d, stdout %r, stderr %r" % (code, out, err))
        check("c: %s names the closest %s" % (" ".join(args), kind), ("did you mean '%s'?" % near) in err and "There are:" in err,
              "no suggestion in: %s" % err)
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:zzzz"])
    check("c: a name that is near nothing has no suggestion, and still the list", code == 2 and "did you mean" not in err and "There are:" in err, (code, err))


# ---- d: colour -------------------------------------------------------------------------------------------------------------

def case_d(w):
    code, out, err = w.forge_cmd(["list"])
    # Control: a version that always paints fails with `escape codes in piped output`.
    check("d: no escape code into a pipe", "\x1b" not in out + err, "escape codes in piped output: %r" % out)
    for args in (["list"], ["list", "multi"]):
        code, shown = w.pty_cmd(args)
        check("d: %s in a terminal is painted (the control of the next check)" % " ".join(args), code == 0 and "\x1b[" in shown,
              "no escape code in a terminal: %r" % shown)
        code, shown = w.pty_cmd(args, NO_COLOR="1")
        check("d: %s in a terminal with NO_COLOR is not painted" % " ".join(args), code == 0 and "\x1b" not in shown and "multi" in shown,
              "escape codes with NO_COLOR: %r" % shown)
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-d"], NO_COLOR="")
    check("d: a dry-run of config into a pipe has no escape code", code == 0 and "\x1b" not in out + err, (code, out, err))


# ---- e: off and on again ---------------------------------------------------------------------------------------------------

def case_e():
    for label, name, skill in (("a common skill", "plain", "toy-common"), ("a skill of an extras row", "multi", "toy-c"),
                               ("a skill of a project's own list", "plain", "toy-d")):
        w = World()
        text0, proj0, h0 = w.forge_text(), w.proj(name), w.settings_hash(name)
        code, out, err = w.forge_cmd(["config", name, "--off", "skill:" + skill, "--apply"])
        h1 = w.settings_hash(name)
        check("e: %s: off exits 0 and the generated settings.local.json changes (the control of the undo)" % label, code == 0 and h1 != h0,
              "exit %d, %r; settings.local.json did not change when the skill went off" % (code, err))
        code, out, err = w.forge_cmd(["config", name, "--on", "skill:" + skill, "--apply"])
        # Control: an undo that forgets a skill fails with `settings.local.json differs after undo`.
        check("e: %s: on again exits 0" % label, code == 0, "exit %d, %r" % (code, err))
        check("e: %s: settings.local.json is the same after the undo" % label, w.settings_hash(name) == h0, "settings.local.json differs after undo")
        same = sorted(w.proj(name)["skills_keep"]) == sorted(proj0["skills_keep"])
        check("e: %s: the project's kept skills are the same after it" % label, same, (w.proj(name)["skills_keep"], proj0["skills_keep"]))
        if skill == "toy-common":
            check("e: %s: forge.json is byte for byte what it was (the empty opt-out row is gone)" % label, w.forge_text() == text0,
                  "forge.json differs after off and on")
    # A server and an option, the same.
    w = World()
    h0, p0 = w.settings_hash("plain"), w.proj("plain")
    args = ["config", "plain", "--off", "server:toy-echo", "--off", "option:ui", "--apply"]
    code, out, err = w.forge_cmd(args)
    check("e: a server and an option go off in one call", code == 0 and w.proj("plain")["servers"] == [] and w.proj("plain")["ui"] is False,
          (code, err, w.proj("plain")))
    code, out, err = w.forge_cmd(["config", "plain", "--on", "server:toy-echo", "--on", "option:ui", "--apply"])
    check("e: and come back", code == 0 and w.proj("plain")["servers"] == ["toy-echo"] and w.proj("plain")["ui"] is True and w.settings_hash("plain") == h0,
          (code, err, w.proj("plain")))
    check("e: the project file is what it was", w.proj("plain") == p0, (w.proj("plain"), p0))


# ---- f: the write rule -----------------------------------------------------------------------------------------------------

def case_f():
    w = World()
    flags = ["config", "plain", "--off", "skill:toy-common", "--off", "server:toy-echo", "--on", "option:command_guard"]
    before = w.tree()
    code, out, err = w.forge_cmd(flags)
    check("f: no terminal and no --apply is exit 0 and says dry-run", code == 0 and "dry-run" in out and "--apply" in out, (code, out, err))
    check("f: and shows the equivalent command", "forge config plain" in out and "--off skill:toy-common" in out, out)
    # Control: a version that writes in the dry-run fails with `dry-run wrote`.
    check("f: and the world did not change", w.tree() == before, "dry-run wrote: %s" % changed(before, w.tree()))
    code, out, err = w.forge_cmd(flags + ["--apply"])
    after = w.tree()
    check("f: --apply writes", code == 0 and w.proj("plain")["servers"] == [] and w.proj("plain")["command_guard"] is True
          and w.doc()["skill_keep"]["common_opt_out"].get("plain.claude.json") == ["toy-common"], (code, out, err))
    code, out, err = w.forge_cmd(flags + ["--apply"])
    check("f: the same call again changes nothing and says so", code == 0 and "nothing to change" in out and w.tree() == after,
          (code, out, err, changed(after, w.tree())))
    w = World()
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-d", "--yes"])
    check("f: --yes writes too", code == 0 and w.proj("plain")["skills_keep"] == ["toy-common"], (code, out, err))
    # In a terminal: the answer decides.
    w = World()
    flags = ["config", "plain", "--off", "skill:toy-d", "--off", "option:ui"]
    for label, answers in (("n", [b"n\r"]), ("a bare Enter", [b"\r"]), ("N", [b"N\r"]), ("the input ending", [b"\x04"]), ("no", [b"no\r"])):
        before = w.tree()
        code, shown = w.pty_cmd(flags, answers)
        # Control: a version that writes without asking in a terminal fails with `wrote without asking`.
        check("f: in a terminal, %s writes nothing" % label, w.tree() == before and "[y/N]" in shown,
              "wrote without asking: %s; shown %r" % (changed(before, w.tree()), shown))
        check("f: and the command still shows what it would have done", "--off skill:toy-d" in shown, shown)
    code, shown = w.pty_cmd(flags, [b"y\r"])
    check("f: in a terminal, y writes", code == 0 and w.proj("plain")["skills_keep"] == ["toy-common"] and w.proj("plain")["ui"] is False,
          (code, shown, w.proj("plain")))
    check("f: and prints the layer and the undo", "forge config plain --on skill:toy-d --on option:ui" in shown, shown)
    # A file that changed while the owner decided is not written over.
    w = World()
    text0 = w.forge_text()

    def touch():
        doc = w.doc()
        doc["skill_keep"]["common_skills"].append("toy-b")  # a skill of the toy home: valid, and not what the plan saw
        write_json(os.path.join(w.forge, "config", "forge.json"), doc)
    code, shown = w.pty_cmd(["config", "plain", "--off", "skill:toy-common"], [b"y\r"], during=touch)
    check("f: a file changed while the owner decided is refused, exit 1, and not written over",
          code == 1 and "changed" in shown and "toy-common" not in json.dumps(w.doc()["skill_keep"]["common_opt_out"]), (code, shown))
    check("f: and the owner's own change is still there", "toy-b" in w.doc()["skill_keep"]["common_skills"], w.doc()["skill_keep"]["common_skills"])
    # A file in another form (here four-space JSON) would be reformatted whole by a write: refused, nothing written.
    w = World()
    path, doc = os.path.join(w.forge, "config", "projects", "plain.claude.json"), w.proj("plain")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=4)
        fh.write("\n")
    before = w.tree()
    code, out, err = w.forge_cmd(["config", "plain", "--off", "option:ui", "--apply"])
    check("f: a project file in another form is refused (exit 1) and not rewritten", code == 1 and "form forge writes" in err and w.tree() == before,
          (code, out, err, changed(before, w.tree())))
    # A write that cannot be done (a checkout that may not write) is refused before anything is changed: a toy that makes may_write say no.
    w = World()
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-d", "--apply"], HOME=w.home, XDG_CONFIG_HOME="/nonexistent-outside")
    check("f: a toy world whose environment points outside it writes nothing", code == 1 and w.proj("plain")["skills_keep"] == ["toy-common", "toy-d"]
          and "nothing written" in out + err, (code, out, err))


# ---- g: a skill that arrives through a set ---------------------------------------------------------------------------------

def case_g():
    w = World()
    before = w.tree()
    args = ["config", "multi", "--off", "skill:toy-a", "--apply"]
    code, out, err = w.forge_cmd(args)
    check("g: a skill from a set is exit 2", code == 2 and out == "", (code, out, err))
    check("g: it names the set", "TOYSET" in err and "toy-a" in err, err)
    check("g: the tree is intact", w.tree() == before, "wrote despite refusal: %s" % changed(before, w.tree()))
    cmds = [l.strip() for l in err.splitlines() if l.strip().startswith("forge config ")]
    check("g: the two commands that work are printed", len(cmds) == 2 and cmds[0] == "forge config multi --off set:TOYSET"
          and cmds[1] == "forge config multi --off set:TOYSET --on skill:toy-b", cmds)
    # A refused flag among accepted ones writes none of them (toy-c is accepted and applied first, toy-a refused after it).
    before = w.tree()
    code, out, err = w.forge_cmd(["config", "multi", "--off", "server:toy-echo", "--off", "skill:toy-c", "--off", "skill:toy-a", "--apply"])
    # Control: a version that writes the first flag before refusing the second fails with `wrote despite refusal`.
    check("g: a call with several flags in which one is refused writes none", code == 2 and w.tree() == before,
          "wrote despite refusal: exit %d; %s" % (code, changed(before, w.tree())))
    code, out, err = w.forge_cmd(["config", "multi", "--off", "skill:toy-a", "--off", "set:TOYSET", "--apply"])
    check("g: ... but with the set switched off in the same call the skill goes", code == 0 and "toy-a" not in w.proj("multi")["skills_keep"],
          (code, out, err))
    for i, cmd in enumerate(cmds):
        c = World()
        argv = shlex.split(cmd)[1:] + ["--apply"]
        code, out, err = c.forge_cmd(argv)
        kept = c.proj("multi")["skills_keep"]
        check("g: printed command %d runs" % (i + 1), code == 0, (cmd, code, out, err))
        check("g: printed command %d: toy-a is off in what is resolved" % (i + 1), "toy-a" not in kept, kept)
        if i == 0:
            check("g: printed command 1: the whole set is off, the rest stays", "toy-b" not in kept and "toy-c" in kept and "toy-common" in kept, kept)
        else:
            check("g: printed command 2: the others of the set stay", "toy-b" in kept and "toy-c" in kept and "toy-common" in kept, kept)
    # A skill that arrives through a set but is also a common skill goes off through the opt-out: no refusal.
    # (SOLO is not in multi's row, so `--on set:SOLO` adds it; its one member has no other member: the first command is the only one.)
    c = World()
    code, out, err = c.forge_cmd(["config", "multi", "--on", "set:SOLO", "--apply"])
    check("g: --on set:NAME adds @NAME to the row", code == 0 and c.doc()["skill_keep"]["extras"]["multi.claude.json"] == ["@TOYSET", "@SOLO", "toy-c"]
          and "toy-e" in c.proj("multi")["skills_keep"], (code, err, c.doc()["skill_keep"]["extras"]["multi.claude.json"]))
    code, out, err = c.forge_cmd(["config", "multi", "--off", "skill:toy-e"])
    check("g: a one-member set: one command", code == 2 and len([l for l in err.splitlines() if l.strip().startswith("forge config ")]) == 1, (code, err))


# ---- k: every printed undo works when run as printed -----------------------------------------------------------------------

def snapshot(w, name):
    """The files an undo must restore, as text. The project file's `skills_keep` is generated (sync_skill_keep.py puts a common
    skill that comes back at the end, whatever its place was), so its order is not compared; the rows of forge.json are."""
    proj = json.loads(read_text(os.path.join(w.forge, "config", "projects", name + ".claude.json")))
    if isinstance(proj.get("skills_keep"), list):
        proj["skills_keep"] = sorted(proj["skills_keep"])
    return {"forge.json": w.forge_text(), "project file": json.dumps(proj, indent=2), "settings.local.json": w.settings_hash(name)}


def undo_lines(out):
    """The commands the output prints as the undo, in order: the line `undo:` and the `then:` lines after it."""
    return [l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith(("undo:", "then:"))]


def case_k():
    cases = (
        ("a common skill", ["plain"], [], ["--off", "skill:toy-common"]),
        ("a skill of an extras row", ["multi"], [], ["--off", "skill:toy-c"]),
        ("a skill of a project's own list", ["plain"], [], ["--off", "skill:toy-d"]),
        ("a skill put on", ["plain"], [], ["--on", "skill:toy-a"]),
        ("a server and an option off", ["plain"], [], ["--off", "server:toy-echo", "--off", "option:ui"]),
        ("a server and an option on", ["plain"], [], ["--on", "server:toy-two", "--on", "option:command_guard"]),
        ("a set off", ["multi"], [], ["--off", "set:TOYSET"]),
        ("a set on", ["multi"], [], ["--on", "set:SOLO"]),
        ("a set off and a skill of it on (the review's input)", ["multi"], [], ["--off", "set:TOYSET", "--on", "skill:toy-b"]),
        ("a set and one of its skills off", ["multi"], [], ["--off", "skill:toy-a", "--off", "set:TOYSET"]),
        ("a profile's skill off", ["profiled", "@x"], [], ["--off", "skill:toy-c"]),
        ("a profile's skill on", ["profiled", "@x"], [], ["--on", "skill:toy-b"]),
        ("a profile's set off and a skill of it on", ["profiled", "@x"], [["profiled", "@x", "--on", "set:TOYSET"]],
         ["--off", "set:TOYSET", "--on", "skill:toy-b"]),
    )
    for label, target, setup, flags in cases:
        w = World()
        name = target[0]
        for step in setup:
            code, out, err = w.forge_cmd(["config"] + step + ["--apply"])
            assert code == 0, "the setup of %s failed: %s%s" % (label, out, err)
        before = snapshot(w, name)
        code, out, err = w.forge_cmd(["config"] + target + flags + ["--apply"])
        check("k: %s: the change exits 0 and changes a file" % label, code == 0 and snapshot(w, name) != before, (code, out, err))
        cmds = undo_lines(out)
        check("k: %s: an undo is printed" % label, bool(cmds), out)
        for cmd in cmds:
            code, out2, err2 = w.forge_cmd(shlex.split(cmd)[1:] + ["--apply"])
            # Control: the old undo (every flag flipped in one command) exits 2 here with `skill 'toy-b' of project 'multi' is kept
            # after the change although it was asked off`.
            check("k: %s: the printed undo `%s` runs" % (label, cmd), code == 0, "exit %d: %s%s" % (code, out2, err2))
        after = snapshot(w, name)
        check("k: %s: after the undo every file is what it was" % label, after == before, "differ: %s" % changed(before, after))


# ---- l: a server whose secret is missing -----------------------------------------------------------------------------------

def case_l():
    w = World()
    reg = dict(REGISTRY, **{"toy-sec": {"type": "stdio", "command": "toy-sec", "args": [], "env": {"K": "${NOPE_MISSING_SECRET}"}}})
    write_json(os.path.join(w.forge, "config", "mcp-registry.json"), {"servers": reg})
    before = w.tree()
    code, out, err = w.forge_cmd(["config", "plain", "--on", "server:toy-sec", "--apply"])
    # Control: before the fix this wrote the project file and then failed with `written, but forge sync plain --apply exits 1`.
    check("l: --on server:X whose registry entry names a missing secret is exit 2 and writes nothing",
          code == 2 and w.tree() == before, "exit %d, wrote: %s; %s%s" % (code, changed(before, w.tree()), out, err))
    check("l: it names the secret variable and where secrets live", "NOPE_MISSING_SECRET" in err and "config/secrets.json" in err, err)
    # The control of the check itself: with the secret there (a toy value), the same call goes through.
    write_json(os.path.join(w.forge, "credentials", "secrets.json"), {"NOPE_MISSING_SECRET": "toy-not-a-secret"})
    code, out, err = w.forge_cmd(["config", "plain", "--on", "server:toy-sec", "--apply"])
    check("l: with the secret in config/secrets.json the same call writes", code == 0 and "toy-sec" in w.proj("plain")["servers"], (code, out, err))
    check("l: and no output carries the value", "toy-not-a-secret" not in out + err, "the secret's value was printed")


# ---- m: the last skills --------------------------------------------------------------------------------------------------------

def case_m():
    for label, name, first, rest in (("an extras row", "profiled", ["skill:toy-common"], ["skill:toy-c", "skill:toy-d"]),
                                     ("a project's own list", "plain", [], ["skill:toy-common", "skill:toy-d"])):
        w = World()
        for f in first:
            code, out, err = w.forge_cmd(["config", name, "--off", f, "--apply"])
            assert code == 0, "the setup of %s failed: %s%s" % (label, out, err)
        before = w.tree()
        code, out, err = w.forge_cmd(["config", name] + [a for f in rest for a in ("--off", f)] + ["--apply"])
        # Control: before the fix this was exit 0 and wrote `skills_keep: []`.
        check("m: %s: taking out every skill is exit 2 and writes nothing" % label, code == 2 and w.tree() == before,
              "exit %d, wrote: %s; %s%s" % (code, changed(before, w.tree()), out, err))
        check("m: %s: and says the project would have no skill at all" % label, "no skill at all" in err and "skills_keep" in err, err)
        code, out, err = w.forge_cmd(["config", name, "--off", rest[0], "--apply"])
        check("m: %s: all but the last one still goes" % label, code == 0, (code, out, err))


# ---- n and o: a write that goes wrong --------------------------------------------------------------------------------------

def case_n():
    w = World()
    path = os.path.join(w.forge, "config", "forge.json")
    before = w.tree()

    def lock():
        os.chmod(path, 0)
    try:
        code, shown = w.pty_cmd(["config", "plain", "--off", "skill:toy-common"], [b"y\r"], during=lock)
    finally:
        os.chmod(path, 0o644)
    # Control: before the fix this was a traceback: `lib.Unreadable: .../forge.json unreadable (... Permission denied ...)`.
    check("n: a file that cannot be read at the write is exit 1, one line, no traceback", code == 1 and "Traceback" not in shown
          and "cannot be read" in shown and "nothing was written" in shown, (code, shown))
    check("n: and nothing was written", w.tree() == before, changed(before, w.tree()))


def case_o():
    w = World()
    projects = os.path.join(w.forge, "config", "projects")
    before = {"forge.json": w.forge_text(), "project": read_text(os.path.join(projects, "multi.claude.json"))}
    os.chmod(projects, 0o555)  # the second file (the project's) cannot be replaced; the first (forge.json) was written
    try:
        code, out, err = w.forge_cmd(["config", "multi", "--off", "set:TOYSET", "--on", "server:toy-two", "--apply"])
    finally:
        os.chmod(projects, 0o755)
    after = {"forge.json": w.forge_text(), "project": read_text(os.path.join(projects, "multi.claude.json"))}
    # Control: with the rollback of `_write` taken out, forge.json keeps the change: "FAIL o: ... forge.json differs".
    check("o: the second write failing is exit 1 and says the earlier file was put back", code == 1 and "the earlier file was put back" in err, (code, out, err))
    check("o: both files are byte for byte as before", after == before, "differ: %s" % [k for k in before if before[k] != after[k]])


# ---- i: a profile's row ----------------------------------------------------------------------------------------------------

def case_i():
    w = World()
    extras0 = w.doc()["skill_keep"]["extras"]["profiled.claude.json"]
    before = w.proj("profiled")
    code, out, err = w.forge_cmd(["config", "profiled", "@x", "--off", "skill:toy-c", "--apply"])
    after = w.proj("profiled")
    check("i: forge config P @x --off skill:s exits 0", code == 0, (code, out, err))
    check("i: the profile's row lost the skill", after["profiles"]["offered"]["x"].get("skills", []) == [], after["profiles"])
    # Control: a version that writes in extras fails with `profile change leaked to the project`.
    check("i: the project's extras row did not change", w.doc()["skill_keep"]["extras"]["profiled.claude.json"] == extras0
          and sorted(after["skills_keep"]) == sorted(before["skills_keep"]), "profile change leaked to the project: %s" % w.doc()["skill_keep"]["extras"])
    code, js, err = w.forge_cmd(["list", "@x", "--json"], cwd=w.pp("profiled"))
    check("i: the profile resolves without it", code == 0 and "toy-c" not in json.loads(js)["skills_keep"] and "toy-a" in json.loads(js)["skills_keep"], (code, js, err))
    code, out, err = w.forge_cmd(["config", "profiled", "@x", "--off", "skill:toy-a", "--apply"])
    check("i: a skill that comes from the profile's definition is refused (exit 2) and says where from",
          code == 2 and "config/profile-defs/x.json" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "profiled", "@x", "--on", "skill:toy-b", "--apply"])
    check("i: --on adds it to the row", code == 0 and w.proj("profiled")["profiles"]["offered"]["x"]["skills"] == ["toy-b"], (code, err, w.proj("profiled")["profiles"]))
    code, out, err = w.forge_cmd(["config", "profiled", "@x", "--off", "option:ui", "--apply"])
    check("i: an option is the project's: refused for a profile", code == 2 and "option" in err, (code, err))
    # From the project's folder, `forge config @x` is the same.
    code, out, err = w.forge_cmd(["config", "@x", "--off", "skill:toy-b", "--apply"], cwd=w.pp("profiled"))
    check("i: forge config @x from the project's folder", code == 0 and w.proj("profiled")["profiles"]["offered"]["x"].get("skills", []) == [], (code, out, err))


# ---- j: the rest -----------------------------------------------------------------------------------------------------------

# What master (3ecfca4) printed for these two, taken from it before forge list changed, byte for byte.
LIST_AT = ("project multi: 3 profile(s), the default is code\n"
           "  code         the project file as it is\n"
           "  toy-b  red   toy B\n"
           "  list   blue  named like the command\n")
CARD_TOY_B = ("profile toy-b of project multi\n"
              "  description   toy B\n"
              "  color         red\n"
              "  skills_keep   toy-a, toy-b, toy-c, toy-common\n"
              "  plugins_keep  p-def@m, toy-plugin@x\n"
              "  servers       toy-echo\n"
              "  permissions   {\"allow\": [\"Read\"]}\n"
              "  env           {\"MCPORTER_CONFIG\": \"@S@/home/.config/mcporter/mcporter.json\", \"TOY_B\": \"1\", \"TOY_ENV\": \"1\"}\n"
              "differs from the default (the project file as it is):\n"
              "  plugins_keep  +toy-plugin@x\n"
              "  permissions   +allow:Read\n"
              "  env           +TOY_B=1\n")


def case_j(w):
    before = w.tree()
    code, out, err = w.forge_cmd(["config", "bare", "--off", "skill:toy-a"])
    check("j: a project that keeps every skill refuses --off skill", code == 2 and "every global skill" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "bare", "--on", "skill:toy-a"])
    check("j: and --on is nothing to do", code == 0 and "nothing to change" in out, (code, out, err))
    code, out, err = w.forge_cmd(["config", "frozen-p", "--off", "skill:toy-common"])
    check("j: a frozen project is refused", code == 2 and "frozen" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "plain", "--off", "skill:toy-d", "--on", "skill:toy-d"])
    check("j: a flag given on and off is refused", code == 2 and "both" in err, (code, err))
    for bad in ("toy-d", "skill:", ":toy-d"):
        code, out, err = w.forge_cmd(["config", "plain", "--off", bad])
        check("j: --off %r is exit 2 and says the form" % bad, code == 2 and "TYPE:NAME" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "plain"])
    check("j: no flag and no terminal is exit 2 naming forge list NAME", code == 2 and "forge list plain" in err, (code, err))
    code, out, err = w.forge_cmd(["config"], cwd=w.pp("plain"))
    check("j: the project of the folder is the default, and the same refusal", code == 2 and "forge list plain" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "--off", "skill:toy-d"], cwd=w.root)
    check("j: a folder that is no project is exit 2", code == 2 and "not inside a project" in err, (code, err))
    code, out, err = w.forge_cmd(["config", "plain", "multi", "--off", "skill:toy-d"])
    check("j: two projects are refused", code == 2, (code, err))
    code, out, err = w.forge_cmd(["list", "plain", "--names"])
    check("j: --names with a project is exit 2", code == 2, (code, out, err))
    code, out, err = w.forge_cmd(["list", "plain", "--session", "abc"])
    check("j: --session with a project is exit 2", code == 2, (code, out, err))
    # forge list @ and @NAME are what master printed: the profiles of the folder's project, byte for byte.
    code, out, err = w.forge_cmd(["list", "@"], cwd=w.pp("multi"))
    check("j: forge list @ is what master printed", (code, out, err) == (0, LIST_AT, ""), (code, out, err))
    code, out, err = w.forge_cmd(["list", "@toy-b"], cwd=w.pp("multi"))
    check("j: forge list @toy-b is what master printed", (code, out, err) == (0, CARD_TOY_B, ""), (code, out, err))
    code, out, err = w.forge_cmd(["list", "@", "--json"], cwd=w.pp("multi"))
    check("j: forge list @ --json is what master printed", code == 0 and [r["name"] for r in json.loads(out)] == ["code", "toy-b", "list"], (code, out, err))
    check("j: no read changed a file of the world", w.tree() == before, "changed: %s" % changed(before, w.tree()))


def attempt(fn, *args):
    """A case that raised (a missing key after a command that failed) is one FAIL naming it, not a traceback that hides the others."""
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001
        check("%s ran to its end" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))


def main():
    w = World()
    for fn in (case_a, case_c, case_d, case_j):
        attempt(fn, w)
    for fn in (case_differing, case_b, case_e, case_f, case_g, case_i, case_k, case_l, case_m, case_n, case_o):
        attempt(fn)
    sandbox.cleanup()
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    print("test_configure: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
