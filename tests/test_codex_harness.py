#!/usr/bin/env python3
"""`codex_harness` in config/forge.json: whether Codex is configured like Claude Code. Read only with
integrations.codex on, and only the JSON true counts (absent, false and "yes" are off).

  on:  forge writes its hook rows into ~/.codex/hooks.json (the rows whose targets name codex, the
       `user_hooks` rows that list it, the ward on the package's own SessionStart entry) and each
       project's MCP servers into <project>/.codex/config.toml.
  off: neither is written. On --apply forge takes out only what it wrote: the hook entries whose command
       EQUALS one it wrote, and in config.toml the [mcp_servers.<name>] tables (and their .env tables)
       whose name is a registry server; a foreign hook, a foreign table, a foreign key and
       [shell_environment_policy] stay, and the file stays too. Kept in both states: the
       .agents/skills links.

Everything runs in-process against a toy HOME, a toy forge.json and a toy config/; nothing real is read or
written (the toy forge.json carries no jev: its setup.py is a private skill).

Seen failing on 3f9febe (no switch: Codex never gets a hook, and a project always gets its config.toml;
this file as it is, run in a plain copy of that commit), 32 of 55 checks red, the other 23 are controls that
pass there (the switch off, codex off, the table lists Codex rows, config.toml with true, a missing
project_path, which is an error in both states). Messages:
  true: "codex_harness true, no file: every Codex row is written -- hooks.json exists False, line '   ~/.codex/
    hooks.json -> no hook of forge's (already current)', wrote [], want [...]" (the same for the second run,
    the dry-run, the ward, the repair of a stale row and the user_hooks row)
  true -> false: "dry-run: says what it would take out, writes nothing -- line '   ~/.codex/hooks.json ->
    no hook of forge's (already current)'" (nothing had been written to take out)
  the reader: "lib.codex_harness: true only with codex on and the JSON true -- {'codex on, true': 'no
    lib.codex_harness', ...}"
  false, absent, "yes", 1: "exit 0, no .codex/config.toml is created -- exit 0, .codex/config.toml exists
    True", and "the line says no MCP server is written for Codex -- lines ['   codex mcp -> .../config.toml
    (2 servers) +gitignore(created) (created)']"
  true -> false over a file of forge's and a user's: "apply: toy-a and toy-b are gone, the foreign server and
    its env stay -- servers ['toy-a', 'toy-b']" (the file was rewritten whole)
  the text edit and the two files that must be left alone: "no mcp.drop_codex_servers"; a link: "exit 1, lines
    ['   ! codex mcp -> ... NOT written: it resolves to ...']"
Negative controls on the finished code, each mutation put back from a copy of the file, the checks that
went red: the switch ignored (24: every false check, hooks and MCP); loosened to truthy (6: "yes" and 1);
the switch read while codex is off (1: the reader); the true branch of write_codex_hooks removed (7); the
Codex ward emptied (1: the package's SessionStart entry stays); the false branch not taking entries out
(2); sync writing config.toml whatever the switch says (17); sync never taking forge's servers out (13);
the final parse-and-compare of drop_codex_servers removed (2: dotted keys, inline table); tables matched
by any name and not the registry's (6: `mine` goes); a link in the path followed (1); the comment above
the next table dropped with the block (2).
"""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("codex-harness-test-")
HOME = os.path.join(TOY, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME  # before the import: HOME-derived constants are computed there
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG", "CODEX_HOME", "XDG_CONFIG_HOME"):
    os.environ.pop(var, None)
os.environ.update(sandbox.GIT_ENV)
sys.argv = sys.argv[:1]
sys.path.insert(0, sandbox.FORGE)
from forge import lib  # noqa: E402
lib.SETTINGS = os.path.join(TOY, "forge-0.json")
with open(lib.SETTINGS, "w", encoding="utf-8") as fh:
    json.dump({"integrations": {k: False for k in lib.INTEGRATIONS}}, fh)
from forge import hooks, mcp, memory, sync  # noqa: E402

assert lib.HOME == HOME, "forge/lib.py saw the real HOME"
hooks.CODEX_HOOKS = os.path.join(HOME, ".codex", "hooks.json")
hooks.USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")

failures, n_cases = [], [0]


def check(label, ok, detail=""):
    n_cases[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, str(detail)[:700]))


# The two Hindsight writers reach a runtime that is not here; nothing else of sync's project loop does.
memory.write_hindsight_config = lambda *a: "   hindsight config (stub)"
memory.check_hindsight_runtime = lambda *a: None

_n = [0]
TOY_ROW = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy/codex_row.py", "timeout": 10,
           "marker": "codex_row.py", "matcher": None, "agents": ["claude", "codex"]}
CLAUDE_ROW = {"event": "UserPromptSubmit", "command": "python3 <ROOT>/toy/claude_row.py", "timeout": 10,
              "marker": "claude_row.py", "matcher": None, "agents": ["claude"]}


def world(codex=True, harness="absent", **top):
    """Point lib at a toy forge.json and reload hooks over it (its rows are computed at import).
    Hindsight and caveman are on so the code's Codex rows exist; `harness` is the value of codex_harness,
    or the string "absent" to leave the key out."""
    _n[0] += 1
    doc = {"integrations": {"codex": codex, "gsd": False, "jev": False, "hindsight": True, "caveman": True},
           "user_settings": {}, "user_hooks": [TOY_ROW, CLAUDE_ROW]}
    if harness != "absent":
        doc["codex_harness"] = harness
    doc.update(top)
    path = os.path.join(TOY, "forge-%d.json" % _n[0])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    lib.SETTINGS = path
    lib.settings.cache_clear()
    importlib.reload(hooks)
    hooks.CODEX_HOOKS = os.path.join(HOME, ".codex", "hooks.json")
    hooks.USER_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
    return hooks


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def seed(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def reset_hooks_file():
    for p in (hooks.CODEX_HOOKS, hooks.CODEX_HOOKS + ".bak"):
        if os.path.exists(p):
            os.remove(p)


def group(cmd, timeout=None, matcher=None):
    h = {"type": "command", "command": cmd}
    if timeout is not None:
        h["timeout"] = timeout
    return dict({"matcher": matcher} if matcher else {}, hooks=[h])


def cmds(doc):
    """{event: [command, ...]} of a hooks.json document."""
    return {ev: [h.get("command") for g in groups for h in g.get("hooks", [])] for ev, groups in doc.get("hooks", {}).items()}


def run_hooks(h, apply=True):
    try:
        return h.write_codex_hooks(lib.Ctx(apply, None, True))
    except Exception as e:  # a crash is a red check, not a traceback
        return "raised %s: %s" % (type(e).__name__, e)


def load_hooks():
    with open(hooks.CODEX_HOOKS, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------------------------- hooks
# 1. codex_harness true: the rows are written. Which rows is the table's own business (the targets that
# name codex); the test asks the module for them, so a row added later is covered.
h = world(harness=True)
want_cmds = sorted({r[1] for r in h.USER_HOOKS if "codex" in r[5]})
claude_only = {r[1] for r in h.USER_HOOKS if "codex" not in r[5]}
check("control: the table holds Codex rows (the two Hindsight ones, caveman's, the user_hooks row) and Claude-only ones",
      len(want_cmds) >= 4 and any("codex-hook.js" in c for c in want_cmds) and any("codex_row.py" in c for c in want_cmds)
      and any("claude_row.py" in c for c in claude_only), "codex %r, claude only %r" % (want_cmds, sorted(claude_only)))
reset_hooks_file()
line = run_hooks(h)
got = sorted(c for cs in (cmds(load_hooks()) if os.path.exists(h.CODEX_HOOKS) else {}).values() for c in cs)
check("codex_harness true, no file: every Codex row is written",
      got == want_cmds, "hooks.json exists %s, line %r, wrote %r, want %r" % (os.path.exists(h.CODEX_HOOKS), line, got, want_cmds))
check("codex_harness true: nothing that is Claude's alone goes in",
      not (set(got) & claude_only), "wrote %r" % (sorted(set(got) & claude_only),))
before = open(h.CODEX_HOOKS, "rb").read() if os.path.exists(h.CODEX_HOOKS) else None
line = run_hooks(h)
check("codex_harness true: a second run is already current and leaves the bytes",
      before is not None and "already current" in str(line) and open(h.CODEX_HOOKS, "rb").read() == before, "line %r" % (line,))
reset_hooks_file()
check("codex_harness true, dry-run: says it would write, writes nothing",
      "would write" in str(run_hooks(h, apply=False)) and not os.path.exists(h.CODEX_HOOKS), "")

# 2. true: the ward takes the package's own SessionStart entry out (it writes deferInitialReflect), a
# foreign entry stays, and a stale copy of a row is repaired.
reset_hooks_file()
ward = 'node "/pkg/dist/codex-sessionstart-hook.js"'
stale = [c for c in want_cmds if "codex-hook.js" in c][0]
seed(h.CODEX_HOOKS, json.dumps({"theme": "toy", "hooks": {
    "SessionStart": [group(ward, 5), group("node /opt/herdr/notify.js", 5)],
    "UserPromptSubmit": [group(stale, 99, "Odd")]}}))
run_hooks(h)
doc = load_hooks() if os.path.exists(h.CODEX_HOOKS) else {}
check("codex_harness true: the package's SessionStart entry is warded off, the foreign one stays",
      ward not in cmds(doc).get("SessionStart", []) and "node /opt/herdr/notify.js" in cmds(doc).get("SessionStart", []),
      "SessionStart %r" % (cmds(doc).get("SessionStart"),))
check("codex_harness true: a stale copy of a row is repaired, another key stays",
      cmds(doc).get("UserPromptSubmit", []).count(stale) == 1 and doc.get("theme") == "toy",
      "UserPromptSubmit %r, theme %r" % (cmds(doc).get("UserPromptSubmit"), doc.get("theme")))
check("codex_harness true: a user_hooks row that lists codex is written, one that does not is not",
      any("codex_row.py" in c for cs in cmds(doc).values() for c in cs)
      and not any("claude_row.py" in c for cs in cmds(doc).values() for c in cs), "wrote %r" % (cmds(doc),))

# 3. true -> false: exactly forge's entries go, the foreign one and the foreign key stay, and a second
# run leaves the bytes (and no .bak of a file with nothing of forge's).
reset_hooks_file()
run_hooks(h)
doc = load_hooks() if os.path.exists(h.CODEX_HOOKS) else {"hooks": {}}
doc["theme"] = "toy"
doc["hooks"].setdefault("UserPromptSubmit", []).append(group("node /opt/herdr/notify.js", 5))
doc["hooks"].setdefault("Stop", []).append(group("node /other/codex-stop-hook.js", 60))
seed(h.CODEX_HOOKS, json.dumps(doc))
h = world(harness=False, user_hooks=[TOY_ROW, CLAUDE_ROW])
want_cmds_false = {r[1] for r in h.USER_HOOKS if "codex" in r[5]}
check("control: the same table, with the switch false, still lists the Codex rows (it is the writer that is gated)",
      set(want_cmds) == want_cmds_false, "%r" % (sorted(want_cmds_false),))
dry_before = open(h.CODEX_HOOKS, "rb").read()
line = run_hooks(h, apply=False)
check("true -> false, dry-run: says what it would take out, writes nothing",
      "would write" in str(line) and open(h.CODEX_HOOKS, "rb").read() == dry_before, "line %r" % (line,))
line = run_hooks(h)
after = load_hooks()
left = sorted(c for cs in cmds(after).values() for c in cs)
check("true -> false: exactly forge's entries are gone, the foreign ones stay",
      left == ["node /opt/herdr/notify.js", "node /other/codex-stop-hook.js"] and after.get("theme") == "toy",
      "left %r, line %r" % (left, line))

# 4. false (absent, false, "yes", 1) with no file: nothing is written. false with a foreign file: untouched.
for label, value in (("false", False), ("absent", "absent"), ('"yes"', "yes"), ("1", 1)):
    hh = world(harness=value)
    reset_hooks_file()
    line = run_hooks(hh)
    check("codex_harness %s, no file: no hook is written" % label,
          not os.path.exists(hh.CODEX_HOOKS) and "already current" in str(line),
          "hooks.json exists %s, line %r" % (os.path.exists(hh.CODEX_HOOKS), line))
hh = world(harness=False)
seed(hh.CODEX_HOOKS, json.dumps({"hooks": {"UserPromptSubmit": [group("node /opt/herdr/notify.js", 5)]}}))
before = open(hh.CODEX_HOOKS, "rb").read()
run_hooks(hh)
check("codex_harness false: a file with nothing of forge's is not rewritten, and gets no .bak",
      open(hh.CODEX_HOOKS, "rb").read() == before and not os.path.exists(hh.CODEX_HOOKS + ".bak"), "")

# 5. Codex off: the switch is not read. NOT RUN, NOT ARMED, and the file is left as it is.
hh = world(codex=False, harness=True)
seed(hh.CODEX_HOOKS, json.dumps({"hooks": {"Stop": [group(want_cmds[0], 5)]}}))
before = open(hh.CODEX_HOOKS, "rb").read()
line = run_hooks(hh)
check("codex off, codex_harness true: NOT RUN, NOT ARMED, the file is not touched",
      "NOT RUN, NOT ARMED" in str(line) and open(hh.CODEX_HOOKS, "rb").read() == before, "line %r" % (line,))
reset_hooks_file()

# 5b. The reader itself: true only with codex on and the key the JSON true; anything else is false.
got = {}
for label, kw in (("codex on, true", dict(codex=True, harness=True)), ("codex on, false", dict(codex=True, harness=False)),
                  ("codex on, absent", dict(codex=True)), ("codex on, \"true\"", dict(codex=True, harness="true")),
                  ("codex off, true", dict(codex=False, harness=True))):
    world(**kw)
    got[label] = getattr(lib, "codex_harness", lambda: "no lib.codex_harness")()
check("lib.codex_harness: true only with codex on and the JSON true",
      got == {"codex on, true": True, "codex on, false": False, "codex on, absent": False, "codex on, \"true\"": False,
              "codex off, true": False}, "%r" % (got,))

# ------------------------------------------------------------------------------------------------- MCP
REGISTRY = {"servers": {"toy-a": {"command": "node", "args": ["a.js"], "env": {"TOY_K": "v"}},
                        "toy-b": {"url": "https://192.0.2.1/mcp"}}}


def repo(d):
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)


def generate(name, apply=True, prepare=None, servers=("toy-a", "toy-b")):
    """One agent_config run over a toy config/ holding the one project `name` (its directory is
    <TOY>/<name>/projects/p). Returns (exit code, output, the project's directory). `prepare(dir)`
    makes the project before the run. The toy forge.json in force is the last world() call's."""
    base = os.path.join(TOY, name)
    cfg, pdir = os.path.join(base, "config"), os.path.join(base, "config", "profiles")
    project = os.path.join(base, "projects", "p")
    os.makedirs(pdir, exist_ok=True)
    seed(os.path.join(cfg, "mcp-registry.json"), json.dumps(REGISTRY))
    seed(os.path.join(base, "secrets.json"), "{}")
    if not os.path.lexists(os.path.join(cfg, "secrets.json")):
        os.symlink(os.path.join(base, "secrets.json"), os.path.join(cfg, "secrets.json"))
    seed(os.path.join(cfg, "project-relocations.json"), '{"relocations": []}')
    os.makedirs(project, exist_ok=True)
    if prepare:
        prepare(project)
    seed(os.path.join(pdir, "p.claude.json"), json.dumps({"project": "p", "servers": list(servers), "project_path": project}))
    sync.CFG, lib.PROFILES = cfg, pdir
    if not os.path.realpath(project).startswith(TOY + os.sep):
        sys.exit("FENCE: %s is outside the toy world -- nothing run" % project)
    ctx = lib.Ctx(apply, None, False)
    lib.context = lambda argv: ctx
    out, code = io.StringIO(), 0
    with contextlib.redirect_stdout(out):
        try:
            code = sync.agent_config([])
        except SystemExit as e:
            code = e.code
        except Exception as e:
            code = "raised %s: %s" % (type(e).__name__, e)
    return code, out.getvalue(), project


def prep(project):
    repo(project)
    seed(os.path.join(project, ".claude", "skills", "s1", "SKILL.md"), "x")


def toml_of(project):
    p = os.path.join(project, ".codex", "config.toml")
    return tomllib.loads(read(p)) if os.path.exists(p) else None


def mcp_line(out):
    return [l for l in out.splitlines() if "codex mcp" in l]


# 6. true: the servers are written, as they always were (the control), and the skills link is made.
world(harness=True)
code, out, proj = generate("mcp-true", prepare=prep)
t = toml_of(proj)
check("codex_harness true: exit 0, .codex/config.toml holds both servers (control: written before the switch too)",
      code == 0 and t is not None and sorted(t.get("mcp_servers", {})) == ["toy-a", "toy-b"],
      "exit %r, servers %r\n%s" % (code, sorted((t or {}).get("mcp_servers", {})), out))
check("codex_harness true: the .agents/skills link is made",
      os.path.islink(os.path.join(proj, ".agents", "skills", "s1")), "")

# 7. false (and absent, "yes", 1): no config.toml is created, the skills link and AGENTS.md's world stay.
for label, value in (("false", False), ("absent", "absent"), ('"yes"', "yes"), ("1", 1)):
    world(harness=value)
    code, out, proj = generate("mcp-%s" % label.strip('"'), prepare=prep)
    check("codex_harness %s: exit 0, no .codex/config.toml is created" % label,
          code == 0 and not os.path.exists(os.path.join(proj, ".codex", "config.toml")),
          "exit %r, .codex/config.toml exists %s\n%s" % (code, os.path.exists(os.path.join(proj, ".codex", "config.toml")), out))
    check("codex_harness %s: the .agents/skills link is made all the same" % label,
          os.path.islink(os.path.join(proj, ".agents", "skills", "s1")), "")
    check("codex_harness %s: the line says no MCP server is written for Codex" % label,
          any("codex_harness off" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))

# 8. false over a config.toml of forge's own and a user's: apply takes out the two servers and nothing
# else. The file is forge's old output (true), plus what a user added around and between it.
world(harness=True)
code, out, proj = generate("mcp-switch", prepare=prep)
cfg_path = os.path.join(proj, ".codex", "config.toml")
generated = read(cfg_path)
FOREIGN_TOP = '# my own codex settings\nmodel = "toy-model"\n\n[profiles.review]\nmodel = "toy-review"\n\n'
FOREIGN_MCP = '\n# a server of mine\n[mcp_servers.mine]\ncommand = "toy-own"\n\n[mcp_servers.mine.env]\nX = "1"\n'
seed(cfg_path, FOREIGN_TOP + generated + FOREIGN_MCP)
os.chmod(cfg_path, 0o600)
before_doc = tomllib.loads(read(cfg_path))
world(harness=False)
before = open(cfg_path, "rb").read()
code, out, proj = generate("mcp-switch", apply=False, prepare=prep)
check("true -> false, dry-run: exit 0, the line says it would update and names the two servers, the bytes are unchanged",
      code == 0 and open(cfg_path, "rb").read() == before
      and any("would update" in l and "toy-a" in l and "toy-b" in l and "mine" not in l for l in mcp_line(out)),
      "exit %r, lines %r" % (code, mcp_line(out)))
code, out, proj = generate("mcp-switch", apply=True, prepare=prep)
t = toml_of(proj)
check("true -> false, apply: exit 0 and the line says it updated",
      code == 0 and any("(updated)" in l for l in mcp_line(out)), "exit %r, lines %r" % (code, mcp_line(out)))
check("true -> false, apply: toy-a and toy-b are gone, the foreign server and its env stay",
      t is not None and sorted(t.get("mcp_servers", {})) == ["mine"] and t["mcp_servers"]["mine"] == before_doc["mcp_servers"]["mine"],
      "servers %r" % (sorted((t or {}).get("mcp_servers", {})),))
check("true -> false, apply: the foreign top key and table stay, and so does what forge wrote that is not an MCP server",
      t is not None and t.get("model") == "toy-model" and t.get("profiles") == before_doc["profiles"]
      and t.get("shell_environment_policy") == before_doc["shell_environment_policy"],
      "keys %r" % (sorted(t or {}),))
text = read(cfg_path)
check("true -> false, apply: the user's comments and text are kept as written",
      "# my own codex settings" in text and "# a server of mine" in text and 'command = "toy-own"' in text
      and "toy-a" not in text and "toy-b" not in text and "a.js" not in text, text)
check("true -> false, apply: the file keeps mode 600 and the once-ever .bak exists",
      (os.stat(cfg_path).st_mode & 0o777) == 0o600 and os.path.exists(cfg_path + ".bak"), "")
check("true -> false, apply: the .agents/skills link is still there",
      os.path.islink(os.path.join(proj, ".agents", "skills", "s1")), "")
before = open(cfg_path, "rb").read()
code, out, proj = generate("mcp-switch", apply=True, prepare=prep)
check("true -> false, a second apply leaves the bytes and says none of forge's is in it",
      open(cfg_path, "rb").read() == before and any("none of forge's" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))

# 9. false over a file that is not forge's to read: a file that does not parse, and one that holds a
# registry server's name in a shape the line reader cannot take out whole, are left as they are.
for label, body in (("not TOML", "[mcp_servers\nbroken"),
                    ("dotted keys under [mcp_servers]", '[mcp_servers]\ntoy-a.command = "node"\n')):
    world(harness=False)
    seed(cfg_path, body)
    code, out, proj = generate("mcp-switch", apply=True, prepare=prep)
    check("false, a file that is %s: left as it is, the line says so, exit 0" % label,
          code == 0 and read(cfg_path) == body and any("left alone" in l for l in mcp_line(out)),
          "exit %r, bytes %r, lines %r" % (code, read(cfg_path), mcp_line(out)))

# 9.0 A profile whose project_path is not a directory is an error in both states, as it was before the
# switch: the '!' line and exit 1 (write_codex_project_mcp's message, kept by drop_codex_project_mcp).
# Red before the line was kept: "false, project_path missing: exit 0, lines []" (the drop said nothing).
for label, value in (("true", True), ("false", False)):
    world(harness=value)
    code, out, proj = generate("mcp-gone-%s" % label, prepare=lambda p: (prep(p), os.rename(p, p + "-moved")))
    check("codex_harness %s, project_path missing: the '!' line says so and the run exits 1" % label,
          code == 1 and any(l.lstrip().startswith("!") and "codex mcp: project_path does not exist on disk" in l
                            for l in out.splitlines()), "exit %r\n%s" % (code, out))

# 9a. A config.toml that is a link is never rewritten through, as the writer never does: the file it points
# at (a tracked one, say) keeps forge's server table and the line says it was not changed.
world(harness=False)


def planted(project):
    prep(project)
    seed(os.path.join(project, "tracked.toml"), '[mcp_servers.toy-a]\ncommand = "node"\n')
    os.makedirs(os.path.join(project, ".codex"))
    os.symlink(os.path.join("..", "tracked.toml"), os.path.join(project, ".codex", "config.toml"))


code, out, proj = generate("mcp-link", prepare=planted)
check("false, .codex/config.toml is a link: the target is untouched and the line says NOT changed",
      read(os.path.join(proj, "tracked.toml")) == '[mcp_servers.toy-a]\ncommand = "node"\n'
      and os.path.islink(os.path.join(proj, ".codex", "config.toml"))
      and any("NOT changed" in l for l in mcp_line(out)), "exit %r, lines %r" % (code, mcp_line(out)))

# 9b. The text edit itself, on a file written the way a person writes one: bare and quoted keys, spaced
# headers, a trailing comment, a comment above the table that follows a dropped one, a name that is not a
# registry server (stays whatever its neighbours do), and no servers table of forge's at all.
NAMES = {"toy-a", "toy-b"}
dcs = getattr(mcp, "drop_codex_servers", lambda text, names: (None, [], "no mcp.drop_codex_servers"))  # a missing function is red checks
TEXT = ('# top\nmodel = "m"\n\n# about toy-a\n[mcp_servers.toy-a]\ncommand = "node"\nargs = [\n  "x",\n]\n\n'
        '[mcp_servers.toy-a.env]\nK = "v"\n\n# keep me, I am about profiles\n[profiles.x]\ny = 1\n\n'
        '[mcp_servers.mine]\ncommand = "z"\n\n [ mcp_servers . "toy-b" ]   # spaced\nurl = "u"\n')
new, dropped, why = dcs(TEXT, NAMES)
tdoc = tomllib.loads(new) if new else {}
check("text edit: both registry servers go whatever the spelling of their header, `mine` stays",
      why is None and dropped == ["toy-a", "toy-b"] and sorted(tdoc.get("mcp_servers", {})) == ["mine"], "%r %r\n%s" % (dropped, why, new))
check("text edit: every comment stays, and so does what the dropped tables did not own",
      all(c in (new or "") for c in ("# top", "# about toy-a", "# keep me, I am about profiles", "[profiles.x]", 'model = "m"')),
      new)
check("text edit: nothing of the dropped tables is left", not any(w in (new or "") for w in ('"node"', '"x"', 'K = "v"', 'url = "u"')), new)
check("text edit: a text with none of forge's servers comes back byte for byte",
      dcs('[mcp_servers.mine]\ncommand = "z"\n', NAMES) == ('[mcp_servers.mine]\ncommand = "z"\n', [], None), "")
check("text edit: the registry decides, not the file: with no names nothing goes",
      dcs(TEXT, set()) == (TEXT, [], None), "")
new, dropped, why = dcs('[mcp_servers.toy-a]\ncommand = "node"\n', NAMES)
check("text edit: a file that held only forge's server is left empty, not removed (the writer's choice is the file's)",
      new == "" and dropped == ["toy-a"], "%r %r" % (new, dropped))
new, dropped, why = dcs('[mcp_servers]\n[mcp_servers.toy-a]\ncommand = "node"\n', NAMES)
check("text edit: an explicit [mcp_servers] header stays when its last child goes",
      "[mcp_servers]" in (new or "") and "toy-a" not in (new or ""), "%r %r" % (new, why))
new, dropped, why = dcs('[mcp_servers.toy-a]\ncommand = "node"\n[mcp_servers]\ntoy-b = { url = "u" }\n', NAMES)
check("text edit: a name set by an inline table in [mcp_servers] cannot be taken out whole, so nothing is changed",
      new is None and why and "shape" in why, "%r %r" % (new, why))

# 10. false, no .codex at all: nothing is created, the line says none of forge's is there.
world(harness=False)
code, out, proj = generate("mcp-none", prepare=prep)
check("false, no .codex/: none is created", not os.path.exists(os.path.join(proj, ".codex")), "")

# 11. codex off, harness true: the switch is not read. No .codex/, and the NOT RUN line.
world(codex=False, harness=True)
code, out, proj = generate("mcp-codex-off", prepare=prep)
check("codex off, codex_harness true: no .codex/, no .agents/, and NOT RUN, NOT ARMED",
      not os.path.lexists(os.path.join(proj, ".codex")) and not os.path.lexists(os.path.join(proj, ".agents"))
      and any("NOT RUN, NOT ARMED" in l and "codex" in l for l in out.splitlines()), out)

failed = bool(failures)
for f in failures:
    print("FAIL", f)
print("%d check(s), %d failure(s)" % (n_cases[0], len(failures)))
sandbox.cleanup(failed)
sys.exit(1 if failed else 0)
