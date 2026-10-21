#!/usr/bin/env python3
"""`codex_harness` in config/forge.json: whether Codex is configured like Claude Code. Read only with
integrations.codex on, and only the JSON true counts (absent, false and "yes" are off).

  on:  forge writes its hook rows into ~/.codex/hooks.json (the rows whose targets name codex, the
       `user_hooks` rows that list it, the ward on the package's own SessionStart entry) and each
       project's MCP servers into <project>/.codex/config.toml.
  off: neither is written. On --apply forge takes out only what it wrote: the hook entries whose command
       EQUALS one it wrote, and in config.toml the [mcp_servers.<name>] tables (and their .env tables)
       whose name is a registry server, the [shell_environment_policy] table of the shape forge writes (it
       holds the profile's env as resolved) and the once-ever config.toml.bak when it holds forge's; a
       foreign hook, a foreign table, a foreign key and a policy table of another shape stay, and the file
       stays too. Kept in both states: the .agents/skills links.

Everything runs in-process against a toy HOME, a toy forge.json and a toy config/; nothing real is read or
written.

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
Section 12 (the policy table and the .bak), seen failing on the commit before it: 22 of 84 checks red, the other
62 are controls that pass there. Messages: "false, apply: no table, no secret in the file, ... the .bak is gone --
lines ['   codex mcp -> ... (codex_harness off: no MCP server written; forge's out: toy-a) (updated)']" (the table
stayed, and so did the .bak); "policy edit: ... -- False 'no mcp.drop_codex_policy'"; "false, a file of forge's
and no .bak: the edit leaves no .bak behind -- dir ['config.toml', 'config.toml.bak']" (the old edit made one,
holding the secret again). Negative controls on the finished code, each put back from a copy: .bak link check
removed (1 red), every parsed .bak taken for forge's (1), any table taken for forge's (5), inherit not checked (1),
foreign set keys accepted (2), MCPORTER_CONFIG not accepted (2), parse-and-compare of the policy edit removed (1),
the edit writing a .bak again (3), the .bak removed in a dry-run too (2), the policy never taken out (10), the
.bak never removed (5), inherit-only accepted while forge would write a set (1).
The .bak is judged by shape and not by today's registry or env, because it holds the OLDEST content and its names
drift (a retired server, a key the profile dropped): a regular file, not behind a link, whose only top-level
keys are mcp_servers and a policy with `inherit = "core"`, or that names a registry server. Seen failing on the
commit that matched names: "false, a .bak drifted: removed, the line says so -- ... (codex_harness off: no MCP
server written, none of forge's in it)" (1 of 88 red, the three foreign .bak controls pass there). Negative
controls: other top-level keys allowed (1 red), inherit not checked (1), a policy not required (1), only
registry names counted (2).
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
    Hindsight and the house hooks are on so the code's Codex rows exist; `harness` is the value of codex_harness,
    or the string "absent" to leave the key out."""
    _n[0] += 1
    doc = {"integrations": {"codex": codex, "gsd": False, "hindsight": True},
           "house_hooks": True, "user_settings": {}, "user_hooks": [TOY_ROW, CLAUDE_ROW]}
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
check("control: the table holds Codex rows (the two Hindsight ones, the house router's, the user_hooks row) and Claude-only ones",
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


def generate(name, apply=True, prepare=None, servers=("toy-a", "toy-b"), env=None, secrets=None):
    """One agent_config run over a toy config/ holding the one project `name` (its directory is
    <TOY>/<name>/projects/p). Returns (exit code, output, the project's directory). `prepare(dir)`
    makes the project before the run. The toy forge.json in force is the last world() call's."""
    base = os.path.join(TOY, name)
    cfg, pdir = os.path.join(base, "config"), os.path.join(base, "config", "profiles")
    project = os.path.join(base, "projects", "p")
    os.makedirs(pdir, exist_ok=True)
    seed(os.path.join(cfg, "mcp-registry.json"), json.dumps(REGISTRY))
    seed(os.path.join(base, "secrets.json"), json.dumps(secrets or {}))
    if not os.path.lexists(os.path.join(cfg, "secrets.json")):
        os.symlink(os.path.join(base, "secrets.json"), os.path.join(cfg, "secrets.json"))
    seed(os.path.join(cfg, "project-relocations.json"), '{"relocations": []}')
    os.makedirs(project, exist_ok=True)
    if prepare:
        prepare(project)
    seed(os.path.join(pdir, "p.claude.json"), json.dumps(dict({"project": "p", "servers": list(servers), "project_path": project}, **({"env": env} if env else {}))))
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
check("true -> false, apply: the foreign top key and table stay, and the [shell_environment_policy] forge wrote goes",
      t is not None and t.get("model") == "toy-model" and t.get("profiles") == before_doc["profiles"]
      and "shell_environment_policy" not in t,
      "keys %r" % (sorted(t or {}),))
text = read(cfg_path)
check("true -> false, apply: the user's comments and text are kept as written",
      "# my own codex settings" in text and "# a server of mine" in text and 'command = "toy-own"' in text
      and "toy-a" not in text and "toy-b" not in text and "a.js" not in text, text)
check("true -> false, apply: the file keeps mode 600 and no .bak is left holding what forge wrote",
      (os.stat(cfg_path).st_mode & 0o777) == 0o600 and not os.path.exists(cfg_path + ".bak"), "")
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

# 12. [shell_environment_policy] and the .bak. With the switch off Codex gets nothing Claude-style from
# forge: the policy table forge wrote (it holds the profile's env as resolved, secrets included) goes with
# the servers, and so does the once-ever .bak forge wrote, which holds the old values. Forge's table is
# recognised by its SHAPE, not its name: `inherit = "core"` and nothing else but a `set` table whose keys
# are all ones forge would write for the profile (the profile's env keys and MCPORTER_CONFIG), or no `set`
# at all when forge would write none. Values are not compared: a rotated secret or an edited profile leaves
# a table whose values are stale and still forge's, and still the one that must go. A table of any other
# shape is a person's, and stays. A .bak is forge's when it is a regular file, not a link, and holds a
# registry server or a table of that shape: what forge's first write replaced. The names below are the
# test's own; the secret is a made-up string.
ENV = {"TOY_TOKEN": "${TOY_SECRET}", "TOY_PLAIN": "p"}
SECRETS = {"TOY_SECRET": "toy-secret-value-xyz"}
OLD_FORGE = ('[shell_environment_policy]\ninherit = "core"\n\n[shell_environment_policy.set]\nTOY_PLAIN = "old"\n'
             'TOY_TOKEN = "toy-secret-value-old"\n\n[mcp_servers.toy-a]\ncommand = "node"\n')
_pn = [0]


def bak_of(proj):
    return os.path.join(proj, ".codex", "config.toml.bak")


def toml_text(proj):
    return read(os.path.join(proj, ".codex", "config.toml"))


def with_config(body, bak=None):
    """A prepare(): the project, its .codex/config.toml holding `body`, and a .codex/config.toml.bak when given."""
    def prepare(project):
        prep(project)
        if body is not None:
            seed(os.path.join(project, ".codex", "config.toml"), body)
        if bak is not None:
            seed(os.path.join(project, ".codex", "config.toml.bak"), bak)
    return prepare


def fresh(prepare, **kw):
    """generate() in a world of its own, so each case starts from its own project."""
    _pn[0] += 1
    return generate("pol-%d" % _pn[0], prepare=prepare, env=kw.pop("env", ENV), secrets=SECRETS, **kw)


# 12a. true with an env writes the table and keeps the .bak (control: nothing changes with the switch on),
# then false takes the table, the secret and the .bak out. The old file is forge's earlier output, so the
# .bak holds its old secret, as a real one does.
world(harness=True)
code, out, proj = generate("pol-switch", prepare=with_config(OLD_FORGE), env=ENV, secrets=SECRETS)
cfg_path = os.path.join(proj, ".codex", "config.toml")
t = toml_of(proj)
check("true, with an env: the policy table holds the resolved secret and the .bak holds the old one (control)",
      t is not None and t["shell_environment_policy"]["set"]["TOY_TOKEN"] == "toy-secret-value-xyz"
      and "toy-secret-value-old" in read(bak_of(proj)), "exit %r, %r" % (code, t))
code, out, proj = generate("pol-switch", prepare=with_config(OLD_FORGE), env=ENV, secrets=SECRETS)
check("true, a second run: policy and .bak stay as they are (control)",
      "toy-secret-value-xyz" in toml_text(proj) and os.path.exists(bak_of(proj)), "")
seed(cfg_path, "# mine\nmodel = \"toy-model\"\n\n" + toml_text(proj))
os.chmod(cfg_path, 0o600)
world(harness=False)
before = open(cfg_path, "rb").read()
code, out, proj = generate("pol-switch", apply=False, prepare=prep, env=ENV, secrets=SECRETS)
check("false, dry-run: the line names the table and the .bak it would take out, and nothing is written",
      code == 0 and open(cfg_path, "rb").read() == before and os.path.exists(bak_of(proj))
      and any("would update" in l and "forge's out: toy-a, toy-b, [shell_environment_policy]" in l
              and ".bak would be removed" in l for l in mcp_line(out)), "exit %r, lines %r" % (code, mcp_line(out)))
check("false, dry-run: no line prints a value", all("toy-secret" not in l for l in out.splitlines()), out)
code, out, proj = generate("pol-switch", apply=True, prepare=prep, env=ENV, secrets=SECRETS)
check("false, apply: no table, no secret in the file, the foreign key stays, the .bak is gone, the line says so",
      code == 0 and "shell_environment_policy" not in toml_text(proj) and "toy-secret" not in toml_text(proj)
      and toml_of(proj) == {"model": "toy-model"} and not os.path.exists(bak_of(proj))
      and any("(updated)" in l and "forge's out: toy-a, toy-b, [shell_environment_policy]" in l
              and ".bak removed" in l for l in mcp_line(out)), "exit %r, lines %r, text %r" % (code, mcp_line(out), toml_text(proj)))
check("false, apply: the user's comment stays", "# mine" in toml_text(proj), toml_text(proj))
before = open(cfg_path, "rb").read()
code, out, proj = generate("pol-switch", apply=True, prepare=prep, env=ENV, secrets=SECRETS)
check("false, a second apply changes nothing and says none of forge's is in it",
      open(cfg_path, "rb").read() == before and any("none of forge's" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))

# 12a2. With no .bak beforehand the edit itself makes none: it would hold the secret again.
code, out, proj = fresh(with_config(OLD_FORGE))
check("false, a file of forge's and no .bak: the edit leaves no .bak behind",
      toml_of(proj) == {} and not os.path.exists(bak_of(proj)), "lines %r, dir %r" % (mcp_line(out), os.listdir(os.path.dirname(cfg_path))))

# 12b. A policy table that is not forge's shape stays, with a line saying so; the servers still go.
FOREIGN_POLICIES = (
    ("inherit all", '[shell_environment_policy]\ninherit = "all"\n[shell_environment_policy.set]\nTOY_PLAIN = "p"\n'),
    ("a key forge would not write", '[shell_environment_policy]\ninherit = "core"\n[shell_environment_policy.set]\nMY_OWN = "1"\n'),
    ("an extra key", '[shell_environment_policy]\ninherit = "core"\nexclude = ["*KEY*"]\n'),
    ("inherit only while forge would write a set", '[shell_environment_policy]\ninherit = "core"\n'),
)
for label, body in FOREIGN_POLICIES:
    text = body + '\n[mcp_servers.toy-a]\ncommand = "node"\n'
    code, out, proj = fresh(with_config(text))
    t = toml_of(proj)
    check("false, a policy with %s: it stays untouched, the server goes, the line says it was left alone" % label,
          code == 0 and t == {k: v for k, v in tomllib.loads(text).items() if k != "mcp_servers"}
          and any("[shell_environment_policy] left alone" in l and "forge's out: toy-a" in l for l in mcp_line(out)),
          "exit %r, lines %r, text %r" % (code, mcp_line(out), toml_text(proj)))

# 12c. forge's table alone (no servers in the file), and a profile with no env, where forge writes the
# inherit key only: that table is forge's too. The line names it and no server.
for label, env, body in (("with a set", ENV, '[shell_environment_policy]\ninherit = "core"\n\n[shell_environment_policy.set]\nTOY_PLAIN = "p"\n'),
                         ("inherit only, a profile with no env", {}, '[shell_environment_policy]\ninherit = "core"\n')):
    code, out, proj = fresh(with_config('model = "m"\n\n' + body), env=env)
    check("false, only forge's policy %s: it goes, the rest stays, the line names it alone" % label,
          code == 0 and toml_of(proj) == {"model": "m"}
          and any("forge's out: [shell_environment_policy]" in l and "toy-a" not in l for l in mcp_line(out)),
          "exit %r, lines %r, text %r" % (code, mcp_line(out), toml_text(proj)))

# 12d. The text edit itself.
dcp = getattr(mcp, "drop_codex_policy", lambda text, names: (None, False, "no mcp.drop_codex_policy"))
PT = ('# top\nmodel = "m"\n\n# about the env\n[shell_environment_policy]   # forge\ninherit = "core"\n\n'
      '[ shell_environment_policy . set ]\nA = "1"\nMCPORTER_CONFIG = "x"\n\n# keep me\n[profiles.x]\ny = 1\n')
new, taken, why = dcp(PT, {"A"})
check("policy edit: both tables go whatever the spelling, every other line and comment stays",
      why is None and taken and tomllib.loads(new or "") == {"model": "m", "profiles": {"x": {"y": 1}}}
      and all(c in (new or "") for c in ("# top", "# about the env", "# keep me", "[profiles.x]")) and "inherit" not in (new or ""), "%r %r\n%s" % (taken, why, new))
check("policy edit: MCPORTER_CONFIG is a key forge writes whatever the profile says",
      dcp('[shell_environment_policy]\ninherit = "core"\n[shell_environment_policy.set]\nMCPORTER_CONFIG = "x"\n', set())[1] is True, "")
check("policy edit: no table is no change, byte for byte",
      dcp('[profiles.x]\ny = 1\n', {"A"}) == ('[profiles.x]\ny = 1\n', False, None), "")
new, taken, why = dcp(PT, {"B"})
check("policy edit: a key that is not the profile's keeps the table, and the reason names the key and no value",
      new == PT and not taken and why and "A" in why and '"1"' not in why, "%r %r" % (taken, why))
new, taken, why = dcp('shell_environment_policy.inherit = "core"\n', set())
check("policy edit: dotted keys cannot be taken out whole, so nothing is changed",
      new == 'shell_environment_policy.inherit = "core"\n' and not taken and why and "shape" in why, "%r %r" % (taken, why))
new, taken, why = dcp('[shell_environment_policy]\ninherit = "core"\nset = { A = "1" }\n', {"A"})
check("policy edit: a set written inline is part of the table's block and goes with it",
      why is None and taken and new == "", "%r %r %r" % (new, taken, why))

# 12e. The .bak. Forge's when it is a regular file holding something forge writes. A foreign one, an
# unreadable one and a link stay; a .bak with no config.toml beside it is judged the same way.
for label, body, gone in (("registry", '[mcp_servers.toy-a]\ncommand = "node"\n', True),
                          ("policy", '[shell_environment_policy]\ninherit = "core"\n[shell_environment_policy.set]\nTOY_PLAIN = "old"\n', True),
                          # The oldest content: a server since retired from the registry and a policy key the
                          # profile no longer carries. Forge's all the same (the writer always wrote the policy).
                          ("drifted", '[shell_environment_policy]\ninherit = "core"\n[shell_environment_policy.set]\nGONE_KEY = "old"\n\n'
                                      '[mcp_servers.retired]\ncommand = "x"\n[mcp_servers.retired.env]\nK = "v"\n', True),
                          ("foreign", 'model = "mine"\n[mcp_servers.mine]\ncommand = "z"\n', False),
                          ("foreign-with-policy", 'model = "mine"\n[shell_environment_policy]\ninherit = "core"\n', False),
                          ("foreign-inherit-all", '[shell_environment_policy]\ninherit = "all"\n[mcp_servers.retired]\ncommand = "x"\n', False),
                          ("foreign-no-policy", '[mcp_servers.retired]\ncommand = "x"\n', False)):
    code, out, proj = fresh(with_config('model = "m"\n', body))
    check("false, a .bak %s: %s" % (label, "removed, the line says so" if gone else "left as it is, no word of it"),
          code == 0 and os.path.exists(bak_of(proj)) != gone
          and (any(".bak removed" in l for l in mcp_line(out)) == gone)
          and not any(".bak left alone" in l for l in mcp_line(out))
          and toml_text(proj) == 'model = "m"\n', "exit %r, lines %r" % (code, mcp_line(out)))
code, out, proj = fresh(with_config(None, "[mcp_servers\nbroken"))
check("false, a .bak that does not parse and no config.toml: left as it is, the line says it could not tell",
      code == 0 and read(bak_of(proj)) == "[mcp_servers\nbroken" and any(".bak left alone" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))
code, out, proj = fresh(with_config(None, '[mcp_servers.toy-a]\ncommand = "node"\n'))
check("false, no config.toml, a .bak of forge's: removed, and no config.toml is created",
      code == 0 and not os.path.exists(bak_of(proj)) and not os.path.exists(os.path.join(proj, ".codex", "config.toml"))
      and any(".bak removed" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))


def linked_bak(project):
    prep(project)
    seed(os.path.join(project, "elsewhere.toml"), '[mcp_servers.toy-a]\ncommand = "node"\n')
    os.makedirs(os.path.join(project, ".codex"), exist_ok=True)
    os.symlink(os.path.join("..", "elsewhere.toml"), os.path.join(project, ".codex", "config.toml.bak"))


code, out, proj = fresh(linked_bak)
check("false, a .bak that is a link: the link and its target stay, the line says so",
      os.path.islink(bak_of(proj)) and read(os.path.join(proj, "elsewhere.toml")) == '[mcp_servers.toy-a]\ncommand = "node"\n'
      and any(".bak left alone" in l and "link" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))

# 12f. A config.toml that is a link: its target keeps the policy, and so does a .bak beside the link.


def linked_config(project):
    prep(project)
    seed(os.path.join(project, "tracked.toml"), PT)
    os.makedirs(os.path.join(project, ".codex"))
    os.symlink(os.path.join("..", "tracked.toml"), os.path.join(project, ".codex", "config.toml"))
    seed(os.path.join(project, ".codex", "config.toml.bak"), '[mcp_servers.toy-a]\ncommand = "node"\n')


code, out, proj = fresh(linked_config)
check("false, .codex/config.toml is a link: the target keeps its policy, the .bak stays, the line says NOT changed",
      read(os.path.join(proj, "tracked.toml")) == PT and os.path.exists(bak_of(proj))
      and any("NOT changed" in l for l in mcp_line(out)), "exit %r, lines %r" % (code, mcp_line(out)))

# 12g. A file that does not parse keeps its policy and its .bak.
code, out, proj = fresh(with_config("[shell_environment_policy\nbroken", '[mcp_servers.toy-a]\ncommand = "node"\n'))
check("false, a config.toml that does not parse: file and .bak are left as they are, the line says so",
      toml_text(proj) == "[shell_environment_policy\nbroken" and os.path.exists(bak_of(proj))
      and any("left alone" in l for l in mcp_line(out)), "lines %r" % (mcp_line(out),))

# 12h. Codex off: the switch is not read, and neither the policy nor the .bak is touched (control).
world(codex=False, harness=False)
code, out, proj = fresh(with_config(OLD_FORGE, OLD_FORGE))
check("codex off: config.toml and .bak are not touched (control)",
      toml_text(proj) == OLD_FORGE and read(bak_of(proj)) == OLD_FORGE, "")

failed = bool(failures)
for f in failures:
    print("FAIL", f)
print("%d check(s), %d failure(s)" % (n_cases[0], len(failures)))
sandbox.cleanup(failed)
sys.exit(1 if failed else 0)
