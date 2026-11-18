#!/usr/bin/env python3
"""4.4 U6: the questions of `forge new NAME` and `forge new @NAME` (forge/ask.py), in the owner's order, and what each answer writes.
Every run is in a toy world of tests/sandbox.py (test_new.World): W/forge with its own config, W/home with four toy skills, W/projects.
A question is answered by recorded keys and lines through tests' own driver (a script that replaces `ask.make_asker` and calls
`forge.cli.main`), so what the owner would press is tested without a terminal, and the flags run through `bin/forge` as an agent runs them.

Assertions, each seen failing once: the control of each runs on every run, in a world whose engine copy is mutated in one place; its
failure message is what is quoted, and the assertion must produce it.
  - the questions come in the owner's order: profiles, sets, skills, servers, memory, stack.
      control (the servers block moved before the skills block): `order: servers before skills`
  - the same data by flags and by recorded keys and lines writes the same project file and the same forge.json row.
      control (the flags' final list kept in the order it was typed): `flags and prompts differ`
  - the final list the owner edited (a skill off, a skill on) is what reaches the file.
      control (the edited list ignored): `edited list did not reach the file`
  - `forge new @NAME` in a made project leaves the profiles row, the project's default label and the definition.
      control (no definition written): `forge new @code left no definition`
  - `forge new @list` makes a profile called list; `@-x`, `@@x` and `@Bad` are refused with the reason and write nothing.
      controls (a reserved word list; no name check): `profile named 'list' rejected`, `profile named '-x' created`
  - a profile with nothing answered and no definition, with no terminal: exit 2 naming every such profile in ONE error, nothing written.
      control (the check taken out): `a profile with nothing was made`
  - a failure after the first write (the project file's step fails) leaves the world as it was, definitions and their folder included.
      control (the definitions' folder not on the undo list): `left behind`
  - a failure after `forge new @NAME` wrote its definition leaves the world as it was.
      control (that rollback taken out): `left behind`
  - the "new profile" row of the `forge config NAME` screen, toggled, asks a name and the questions and leaves the profile.
      control (the row does nothing): `the new-profile row made no profile`
  - the plan shows every answer, and the dry-run writes nothing.
      control (a plan without the answers): `the plan does not show`
Also: the old behaviour (no new flag, no terminal) is test_new.py's, unchanged.

Seen failing first (this file, before forge/ask.py existed): `forge new demo --profiles code ...` died with `unrecognized arguments:
--profiles code` (exit 2) and every assertion failed."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
import test_new  # noqa: E402
from test_new import World, tail  # noqa: E402

failures, n_checks = [], [0]
ASK = os.path.join("forge", "ask.py")
NEW = os.path.join("forge", "new.py")

# What the owner would press, per question. The toy skills in W/home/.claude/skills sort as alpha, beta, delta, gamma; the sets are
# ARCH_SET = alpha, beta and OTHER_SET = gamma; the registry holds analytics-demo, plain (and analytics-other, another project's).
DRIVER = '''import builtins, io, json, sys
sys.path.insert(0, sys.argv[1])
from forge import ask, cli
spec = json.load(open(sys.argv[2]))
if spec.get("confirm") is not None:  # what is typed at the `make it?` prompt (configure._ask reads stdin)
    sys.stdin = io.StringIO(spec["confirm"] + "\\n")
if spec.get("interrupt"):  # Ctrl-C at the first `input()` question
    def stop(prompt=""):
        raise KeyboardInterrupt
    builtins.input = stop
made = []
def make():
    asker = ask.Asker(keys=spec["keys"], lines=None if spec.get("interrupt") else spec["lines"], interactive=True)
    made.append(asker)
    return asker
ask.make_asker = make
code = cli.main(spec["argv"])
print("ASKED " + json.dumps(made[-1].asked if made else []))
sys.exit(code)
'''
# The screen of `forge config demo` with a recorded key sequence, then the name and the questions of its "new profile" row.
SCREEN_DRIVER = '''import argparse, builtins, json, sys
sys.path.insert(0, sys.argv[1])
from forge import ask, configure, selector
spec = json.load(open(sys.argv[2]))
real = selector.run
selector.run = lambda sections, window=None, keys=None, **kw: real(sections, window=window, keys=spec["screen_keys"] if keys is None else keys)
configure.has_terminal = lambda: True
configure._ask = lambda prompt: True
def typed(prompt=""):
    if spec.get("interrupt"):  # Ctrl-C at the name of the new profile
        raise KeyboardInterrupt
    return spec["name"]
builtins.input = typed
ask.make_asker = lambda: ask.Asker(keys=spec["keys"], lines=[], interactive=True)
sys.exit(configure.cmd_config(argparse.Namespace(targets=["demo"], on=None, off=None, apply=False, yes=False, json=False)))
'''
ORDER = ["profiles", "sets", "skills", "servers", "memory", "stack"]


def answered(**over):
    """The flags of the four questions that `forge new` wants all of once one of them is given, each `none` unless `over` says otherwise
    (a value None leaves the flag out)."""
    flags = dict({"profiles": "none", "sets": "none", "server": "none", "memory": "none"}, **over)
    return [x for k, v in flags.items() if v is not None for x in ("--" + k, v)]


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def prep(w, hindsight=False, mempalace=False):
    """The world's skills, sets, registry and two other projects; hindsight or mempalace on only where a test asks (a sync then cannot
    finish). The registry's names are what the tests of an account server need: analytics-my-other (suffix `-other`, the name a project
    my-other would own), vercel-el-hero (another project's, whose name ends with a shorter project's: hero), plain and plain-demo (the
    same kind of server twice)."""
    for n in ("alpha", "beta", "gamma", "delta"):
        os.makedirs(os.path.join(w.home, ".claude", "skills", n))
        with open(os.path.join(w.home, ".claude", "skills", n, "SKILL.md"), "w") as fh:
            fh.write("---\nname: %s\ndescription: toy\n---\n" % n)
    path = w.path("config", "forge.json")
    doc = test_new.read_json(path)
    doc["skill_keep"]["sets"] = {"ARCH_SET": ["alpha", "beta"], "OTHER_SET": ["gamma"]}
    doc["skill_keep"]["set_docs"] = {"ARCH_SET": "architecture skills"}
    doc["integrations"]["hindsight"] = hindsight
    doc["integrations"]["mempalace"] = mempalace
    write_json(path, doc)
    stdio = {"type": "stdio", "command": "true", "args": []}
    write_json(w.path("config", "mcp-registry.json"), {"servers": {n: dict(stdio) for n in (
        "analytics-demo", "analytics-other", "analytics-my-other", "vercel-el-hero", "plain", "plain-demo", "mempalace",
        "hindsight-coding-agents", "hindsight-recall")}})
    for name in ("other", "el-hero"):
        folder = os.path.join(w.top, name)
        os.makedirs(folder)
        write_json(w.path("config", "projects", "%s.claude.json" % name), {"project": name, "project_path": folder,
                                                                         "writes_tracked_files": False, "servers": []})


def write_driver(w):
    d = os.path.join(w.top, "driver")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "driver.py"), "w") as fh:
        fh.write(DRIVER)
    write_json(os.path.join(d, "spec.json"), {})
    return d


def asked_run(w, argv, keys, lines, **extra):
    """(exit code, output, the questions asked) of `forge argv` with the owner's recorded answers (`extra`: confirm, interrupt)."""
    d = write_driver(w)
    write_json(os.path.join(d, "spec.json"), dict({"argv": argv, "keys": keys, "lines": lines}, **extra))
    r = subprocess.run([sys.executable, os.path.join(d, "driver.py"), w.root, os.path.join(d, "spec.json")], cwd=w.cwd, env=w.env,
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    asked = next((json.loads(l[6:]) for l in out.splitlines() if l.startswith("ASKED ")), None)
    return r.returncode, out, asked


def project_doc(w, name="demo"):
    return test_new.read_json(w.path("config", "projects", "%s.claude.json" % name))


def row_of(w, name="demo"):
    return ((test_new.read_json(w.path("config", "forge.json")).get("skill_keep") or {}).get("extras") or {}).get("%s.claude.json" % name)


def comparable(w):
    doc = project_doc(w) or {}
    doc.pop("project_path", None)
    return json.dumps(doc, sort_keys=True), json.dumps(row_of(w))


FULL_KEYS = [["space", "enter"],                 # sets: ARCH_SET
             ["enter"],                          # final list: the set's members as they are
             ["space", "enter"],                 # servers: analytics-demo
             ["enter"],                          # memory: none (hindsight is off here, so it is not offered)
             ["enter"]]                          # stack: nothing
PROJECT_LINES = [""]                             # profiles: none


def a_order(w):
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--apply"], [list(k) for k in FULL_KEYS], list(PROJECT_LINES))
    bad = []
    if asked is None:
        return ["the driver did not report the questions: %s" % tail(out)]
    if "servers" in asked and "skills" in asked and asked.index("servers") < asked.index("skills"):
        bad.append("order: servers before skills (%s)" % asked)
    elif asked != ORDER:
        bad.append("order: asked %s, want %s" % (asked, ORDER))
    return bad


def a_same_by_flags_and_prompts(w):
    """w makes `byflags` by flags, then `byprompts` by the same data recorded as keys and lines, in two projects of one world; the
    files compare with the project's own path and name left out."""
    bad = []
    # the final list is typed out of order on purpose: the file must not depend on how it was typed
    code, out = w.forge("new", "byflags", "--stack", "generic", "--sets", "ARCH_SET", "--skills", "gamma,delta,alpha,beta", "--server",
                        "plain", "--memory", "none", "--profiles", "none", "--apply")
    if code != 0:
        bad.append("flags: exit %d: %s" % (code, tail(out)))
    keys = [["space", "enter"],                  # sets: ARCH_SET
            ["down", "down", "space", "down", "space", "enter"],   # final list: alpha, beta on already; delta and gamma on
            ["down", "space", "enter"],          # servers: analytics-demo, plain -> plain
            ["enter"],                           # memory: none
            ["enter"]]                           # stack: nothing
    code, out, asked = asked_run(w, ["new", "byprompts", "--stack", "generic", "--apply"], keys, [""])
    if code != 0:
        bad.append("prompts: exit %d: %s" % (code, tail(out)))
    a, b = comparable_pair(w, "byflags", "byprompts")
    if a != b:
        bad.append("flags and prompts differ: %s | %s" % (a, b))
    return bad


def comparable_pair(w, one, two):
    out = []
    for name in (one, two):
        doc = project_doc(w, name) or {}
        for k in ("project", "project_path"):
            doc.pop(k, None)
        out.append((json.dumps(doc, sort_keys=True), json.dumps(row_of(w, name))))
    return out


def a_edited_list(w):
    keys = [["space", "enter"],                  # sets: ARCH_SET (alpha, beta)
            ["down", "space", "down", "down", "space", "enter"],  # final list: beta off, gamma on -> alpha, gamma
            ["enter"], ["enter"], ["enter"]]
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--apply"], keys, [""])
    row = row_of(w)
    if code != 0 or row != ["alpha", "gamma"]:
        return ["edited list did not reach the file: exit %d, row %s: %s" % (code, row, tail(out))]
    return []


def made_demo(w):
    code, out = w.forge("new", "demo", "--stack", "generic", "--apply")
    return [] if code == 0 else ["demo was not made: exit %d: %s" % (code, tail(out))]


def a_profile_here(w):
    bad = made_demo(w)
    if bad:
        return bad
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--server", "analytics-demo", "--apply", cwd=w.project("demo"))
    doc = project_doc(w) or {}
    want = {"default": "default", "offered": {"code": {"skills": ["@ARCH_SET"], "servers": {"analytics": "analytics-demo"}}}}
    if code != 0 or doc.get("profiles") != want:
        bad.append("forge new @code: exit %d, profiles %s, want %s: %s" % (code, doc.get("profiles"), want, tail(out)))
    d = test_new.read_json(w.path("config", "profile-defs", "code.json"))
    if d is None:
        bad.append("forge new @code left no definition")
    elif d.get("server_kinds") != ["analytics"]:
        bad.append("the definition's server kinds are %s, want ['analytics']" % d.get("server_kinds"))
    code, out = w.forge("list", "@code", cwd=w.project("demo"))
    if code != 0 or "alpha" not in out or "analytics-demo" not in out:
        bad.append("forge list @code does not resolve it: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--apply", cwd=w.project("demo"))
    if code != 2 or "already offers" not in out:
        bad.append("a profile made twice: exit %d, want 2 'already offers': %s" % (code, tail(out)))
    return bad


def a_profile_names(w):
    bad = made_demo(w)
    if bad:
        return bad
    code, out = w.forge("new", "@list", "--sets", "OTHER_SET", "--server", "none", "--apply", cwd=w.project("demo"))
    if code != 0 or "list" not in ((project_doc(w) or {}).get("profiles") or {}).get("offered", {}):
        bad.append("profile named 'list' rejected: exit %d: %s" % (code, tail(out)))
    before = w.snapshot()
    for arg, reason in (("@-x", "starts with -"), ("@@x", "starts with @"), ("@Bad", "kebab-case"), ("@default", "label")):
        code, out = w.forge("new", arg, "--sets", "OTHER_SET", "--server", "none", "--apply", cwd=w.project("demo"))
        if code != 2 or reason not in out:
            bad.append("profile named '%s' created or refused without the reason %r: exit %d: %s" % (arg[1:], reason, code, tail(out)))
    if w.snapshot() != before:
        bad.append("a refused profile name wrote: %s" % test_new.changed(before, w.snapshot())[:4])
    return bad


def a_nothing_answered(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--profiles", "code,docs", "--sets", "none", "--server", "none", "--memory", "none",
                        "--apply")
    bad = []
    if code != 2 or "@code" not in out or "@docs" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("a profile with nothing was made or not named in one error: exit %d: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("a profile with nothing was made: it wrote %s" % test_new.changed(before, w.snapshot())[:4])
    # --stack missing and the answers missing: one error naming both
    code, out = w.forge("new", "demo", "--profiles", "code", "--apply")
    if code != 2 or "--stack" not in out or "@code" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("--stack and the profile's answer not named together: exit %d: %s" % (code, tail(out)))
    return bad


def a_partial_answers(w):
    """One question flag given, no terminal or --yes: every other question must be answered by its flag, all named in one error."""
    bad = []
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--sets", "ARCH_SET", "--apply")
    if (code != 2 or any(f not in out for f in ("--profiles", "--server", "--memory")) or len([l for l in out.splitlines() if l.strip()]) != 1):
        bad.append("a partial answer: exit %d, want 2 naming --profiles, --server and --memory in one line: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("a partial answer wrote %s" % test_new.changed(before, w.snapshot())[:4])
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--profiles", "none", "--yes", "--apply"], [], [])
    if code != 2 or "--server" not in out or asked != []:
        bad.append("--yes in a terminal with one answer: exit %d, asked %s, want 2 naming --server: %s" % (code, asked, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "generic", "--ui", "--apply")
    if code != 2 or "--memory" not in out:
        bad.append("a stack flag alone: exit %d, want 2 naming --memory: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "generic")  # no new flag: as on master
    if code != 0 or "PLAN" not in out:
        bad.append("no new flag: exit %d, want the plan of master: %s" % (code, tail(out)))
    bad += made_demo(w)
    before = w.snapshot()
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--apply", cwd=w.project("demo"))
    if code != 2 or "--server" not in out or w.snapshot() != before:
        bad.append("forge new @code with the sets and no --server: exit %d, want 2 naming --server and nothing written: %s" % (code, tail(out)))
    return bad


def a_resolves(w):
    """A profile is resolved as it will be before the first write: a definition that does not resolve, or that gives nothing, is refused."""
    bad = made_demo(w)
    if bad:
        return bad
    defs = w.path("config", "profile-defs")
    os.makedirs(defs)
    for text, flags, needle in (({"skills": ["@NOPE", "ghost"]}, ["--sets", "ARCH_SET", "--server", "none"], "@NOPE"),
                                ({"description": "x"}, [], "resolves to nothing")):
        write_json(os.path.join(defs, "code.json"), text)
        before = w.snapshot()
        code, out = w.forge("new", "@code", *flags, "--apply", cwd=w.project("demo"))
        if code != 2 or needle not in out or w.snapshot() != before:
            bad.append("unresolved profile was written: definition %s, exit %d, want 2 naming %r and nothing written: %s" % (
                text, code, needle, tail(out)))
    return bad


def a_failure_after_write(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--profiles", "code", "--sets", "ARCH_SET",
                        "--server", "none", "--memory", "none", "--apply")
    bad = []
    if code != 1 or "injected" not in out:
        bad.append("the injected failure did not stop the run: exit %d: %s" % (code, tail(out)))
    after = w.snapshot()
    if after != before:
        bad.append("left behind: %s" % ", ".join(test_new.left_behind(before, after)[:6]))
    return bad


def a_profile_failure(w):
    """`forge new @code` fails after its definition was written: the definition, its folder and the project file are as they were."""
    bad = made_demo(w)
    if bad:
        return bad
    before = w.snapshot()
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--server", "none", "--apply", cwd=w.project("demo"))
    if code != 1 or "injected" not in out:
        bad.append("the injected failure did not stop the run: exit %d: %s" % (code, tail(out)))
    after = w.snapshot()
    if after != before:
        bad.append("left behind: %s" % ", ".join(test_new.left_behind(before, after)[:6]))
    return bad


def a_screen_row(w):
    """The "new profile" row of the `forge config demo` screen: toggled, it asks a name and the questions and leaves the profile."""
    bad = made_demo(w)
    if bad:
        return bad
    d = write_driver(w)
    with open(os.path.join(d, "screen.py"), "w") as fh:
        fh.write(SCREEN_DRIVER)
    write_json(os.path.join(d, "screen.json"), {"screen_keys": ["down"] * 60 + ["space", "enter"], "name": "docs",
                                                "keys": [["space", "enter"], ["enter"], ["enter"]]})
    r = subprocess.run([sys.executable, os.path.join(d, "screen.py"), w.root, os.path.join(d, "screen.json")], cwd=w.cwd, env=w.env,
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    offered = ((project_doc(w) or {}).get("profiles") or {}).get("offered")
    if r.returncode != 0 or offered != {"docs": {"skills": ["@ARCH_SET"]}}:
        bad.append("the new-profile row made no profile: exit %d, offered %s: %s" % (r.returncode, offered, tail(r.stdout + r.stderr)))
    return bad


def a_plan_shows_answers(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "next", "--profiles", "code", "--sets", "ARCH_SET", "--server", "analytics-demo",
                        "--memory", "none", "--check", "pnpm lint", "--plugin", "vercel@claude-plugins-official", "--ui")
    bad = []
    for needle in ("profile     @code", "skills @ARCH_SET", "analytics=analytics-demo", "checks      pnpm lint", "plugins     only vercel@claude-plugins-official",
                   "options     ui"):
        if needle not in out:
            bad.append("the plan does not show %r: %s" % (needle, tail(out, 12)))
    if code != 0 or w.snapshot() != before:
        bad.append("the dry-run: exit %d, wrote %s" % (code, test_new.changed(before, w.snapshot())[:4]))
    return bad


def a_stack_and_memory(w):
    bad = []
    code, out = w.forge("new", "demo", "--stack", "next", *answered(), "--check", "pnpm nope", "--plugin", "nope@x")
    for needle in ("pnpm nope", "nope@x"):
        if code != 2 or needle not in out:
            bad.append("a wrong %s: exit %d: %s" % (needle, code, tail(out)))
    for name, needle in (("nope", "nope"), ("hindsight", "off in config/forge.json"), ("mempalace", "off in config/forge.json")):
        code, out = w.forge("new", "demo", "--stack", "next", *answered(memory=name))
        if code != 2 or needle not in out or "no memory" in out and name != "nope":
            bad.append("--memory %s with the integration off: exit %d, want 2 saying %r: %s" % (name, code, needle, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", *answered(server="analytics-other"))
    if code != 2 or "account server of project other" not in out:
        bad.append("another project's account server: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", *answered(sets="NOPE"))
    if code != 2 or "NOPE" not in out:
        bad.append("an unknown set: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", *answered(sets="@code:ARCH_SET"))
    if code != 2 or "not one of the profiles" not in out:
        bad.append("a scope that names no profile: exit %d: %s" % (code, tail(out)))
    return bad


def a_own_account_server(w):
    """A server is another project's when it ends with that project's name, but a project's own `<service>-<name>` is its own, and the
    longest project name wins (hero does not take vercel-el-hero, which is el-hero's)."""
    bad = []
    code, out = w.forge("new", "my-other", "--stack", "generic", *answered(server="analytics-my-other"))
    if code != 0 or "servers     analytics-my-other" not in out:
        bad.append("the own account server of my-other refused: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "hero", "--stack", "generic", *answered(server="vercel-el-hero"))
    if code != 2 or "account server of project el-hero" not in out:
        bad.append("another project's account server taken by a shorter name: exit %d: %s" % (code, tail(out)))
    return bad


def a_memory_mempalace(w):
    """MemPalace on: it is a memory choice (asked, and by --memory), written into `servers`, and the registry server mempalace is not an
    ordinary row of the servers question nor an answer of --server."""
    bad = []
    keys = [["enter"], ["enter"],                           # sets, final list: nothing
            ["down", "space", "enter"],                     # servers: the second row (analytics-demo, plain): never mempalace
            ["down", "space", "up", "space", "enter"],      # memory: none off, mempalace on
            ["enter"]]                                      # stack
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--apply"], keys, [""])
    servers = (project_doc(w) or {}).get("servers")
    if servers != ["plain", "mempalace"]:
        bad.append("asked: servers %s, want ['plain', 'mempalace'] (exit %d): %s" % (servers, code, tail(out)))
    code, out = w.forge("new", "flags", "--stack", "generic", *answered(memory="mempalace"), "--apply")
    servers = (project_doc(w, "flags") or {}).get("servers")
    if servers != ["mempalace"]:
        bad.append("--memory mempalace: servers %s, want ['mempalace'] (exit %d): %s" % (servers, code, tail(out)))
    code, out = w.forge("new", "ordinary", "--stack", "generic", *answered(server="mempalace"))
    if code != 2 or "--memory mempalace" not in out:
        bad.append("--server mempalace: exit %d, want 2 pointing at --memory mempalace: %s" % (code, tail(out)))
    return bad


def a_one_backend(w):
    """A project never ends with two memory backends: --plugin claude-mem-lite with a memory integration is refused."""
    stack = os.path.join(w.root, "examples", "stacks", "mem")
    os.makedirs(stack)
    write_json(os.path.join(stack, "stack.json"), {"description": "toy", "servers": [], "plugins": ["claude-mem-lite@sdsrss"], "checks": [],
                                                  "skill_sets": []})
    with open(os.path.join(stack, "gitignore"), "w") as fh:
        fh.write(".env\n")
    code, out = w.forge("new", "demo", "--stack", "mem", *answered(memory="mempalace"), "--plugin", "claude-mem-lite@sdsrss")
    if code != 2 or "one per project" not in out:
        return ["two memory backends: exit %d, want 2 saying one per project: %s" % (code, tail(out))]
    code, out = w.forge("new", "demo", "--stack", "mem", *answered(), "--plugin", "claude-mem-lite@sdsrss")
    return [] if code == 0 else ["the memory plugin alone refused: exit %d: %s" % (code, tail(out))]


def a_memory_hindsight(w):
    """Hindsight on: the memory servers reach the project file (the sync that follows cannot finish in a toy world, so the exit is not 0)."""
    code, out = w.forge("new", "demo", "--stack", "generic", *answered(memory="hindsight"), "--apply")
    doc = project_doc(w) or {}
    if doc.get("servers") != ["hindsight-coding-agents", "hindsight-recall"]:
        return ["--memory hindsight left servers %s: exit %d: %s" % (doc.get("servers"), code, tail(out))]
    return []


def a_cancelled(w):
    before = forge_only(w.snapshot())
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--apply"], [["esc"]], ["code"])
    if code != 1 or "cancelled" not in out or forge_only(w.snapshot()) != before:
        return ["Esc at a question: exit %d, want 1 'cancelled' and nothing written: %s" % (code, tail(out))]
    return []


def forge_only(snap):  # the driver and its spec are the test's own files, not something forge wrote
    return {k: v for k, v in snap.items() if not k.startswith("driver")}


def a_set_docs_type(w):
    """skill_keep.set_docs of the wrong type: one line, exit 2, nothing written (a traceback is exit 1 with `Traceback`)."""
    path = w.path("config", "forge.json")
    doc = test_new.read_json(path)
    bad = []
    for wrong in ("oops", ["a"]):
        doc["skill_keep"]["set_docs"] = wrong
        write_json(path, doc)
        before = w.snapshot()
        code, out = w.forge("new", "demo", "--stack", "generic", *answered(sets="ARCH_SET"), "--apply")
        if (code != 2 or "set_docs" not in out or "Traceback" in out or len([l for l in out.splitlines() if l.strip()]) != 1
                or w.snapshot() != before):
            bad.append("set_docs %r: exit %d, want 2, one line naming set_docs, nothing written: %s" % (wrong, code, tail(out)))
    return bad


def a_ctrl_c(w):
    """Ctrl-C at a question that reads a line (the profiles of forge new, the name of the screen's new profile): one line, exit 130, nothing
    written."""
    bad = made_demo(w)
    if bad:
        return bad
    before = forge_only(w.snapshot())
    code, out, asked = asked_run(w, ["new", "other-demo", "--stack", "generic", "--apply"], [], [], interrupt=True)
    if code != 130 or "Traceback" in out or forge_only(w.snapshot()) != before:
        bad.append("Ctrl-C at the profiles question: exit %d, want 130, no traceback and nothing written: %s" % (code, tail(out)))
    d = write_driver(w)
    with open(os.path.join(d, "screen.py"), "w") as fh:
        fh.write(SCREEN_DRIVER)
    write_json(os.path.join(d, "screen.json"), {"screen_keys": ["down"] * 60 + ["space", "enter"], "name": "docs", "keys": [], "interrupt": True})
    before = forge_only(w.snapshot())
    r = subprocess.run([sys.executable, os.path.join(d, "screen.py"), w.root, os.path.join(d, "screen.json")], cwd=w.cwd, env=w.env,
                       capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    if r.returncode != 130 or "Traceback" in r.stderr or forge_only(w.snapshot()) != before:
        bad.append("Ctrl-C at the name of the new profile: exit %d, want 130, no traceback and nothing written: %s" % (
            r.returncode, tail(r.stdout + r.stderr)))
    return bad


def a_sets_alone(w):
    """`--sets` alone answers the lists question (the final list is its members), as `--skills` alone does: nothing else is asked, and the
    stack question is skipped, because every answer came by flag."""
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", *answered(sets="ARCH_SET", server="plain"), "--apply"], [], [])
    row = row_of(w)
    if code != 0 or asked != [] or row != ["@ARCH_SET"]:
        return ["--sets alone in a terminal: exit %d, asked %s (want none), row %s: %s" % (code, asked, row, tail(out))]
    return []


def a_stack_question(w):
    """The stack question is skipped only when every other answer came by flag."""
    bad = []
    flags = ["--stack", "generic", "--apply"]
    code, out, asked = asked_run(w, ["new", "one", *flags, *answered(memory=None, server="plain")], [["enter"], ["enter"]], [])
    if asked != ["memory", "stack"]:
        bad.append("memory unanswered: asked %s, want ['memory', 'stack'] (exit %d): %s" % (asked, code, tail(out)))
    code, out, asked = asked_run(w, ["new", "two", *flags, *answered(server="plain")], [], [])
    if asked != []:
        bad.append("every answer by flag: asked %s, want nothing (exit %d): %s" % (asked, code, tail(out)))
    return bad


def a_scoped(w):
    """A value scoped `@code:` replaces the unscoped one for that profile and stays out of the others; the unscoped one does not also reach
    `code`."""
    code, out = w.forge("new", "demo", "--stack", "generic", *answered(profiles="code,docs", sets="ARCH_SET"), "--sets", "@code:OTHER_SET", "--apply")
    got = ((project_doc(w) or {}).get("profiles") or {}).get("offered")
    want = {"code": {"skills": ["@OTHER_SET"]}, "docs": {"skills": ["@ARCH_SET"]}}
    return [] if got == want else ["scoped sets: profiles %s, want %s (exit %d): %s" % (got, want, code, tail(out))]


def a_confirm_no(w):
    """`n` at the `make it?` prompt writes nothing; `y` makes the project."""
    bad = []
    before = forge_only(w.snapshot())
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic"], [list(k) for k in FULL_KEYS], list(PROJECT_LINES), confirm="n")
    if code != 0 or "nothing written" not in out or forge_only(w.snapshot()) != before or os.path.lexists(w.project("demo")):
        bad.append("n at make it: exit %d, want 0, 'nothing written' and no file: %s" % (code, tail(out)))
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic"], [list(k) for k in FULL_KEYS], list(PROJECT_LINES), confirm="y")
    if not os.path.isdir(w.project("demo")):
        bad.append("y at make it made nothing: exit %d: %s" % (code, tail(out)))
    return bad


def a_frozen(w):
    bad = made_demo(w)
    if bad:
        return bad
    path = w.path("config", "projects", "demo.claude.json")
    doc = project_doc(w)
    doc["frozen"] = True
    write_json(path, doc)
    before = w.snapshot()
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--server", "none", "--apply", cwd=w.project("demo"))
    if code != 2 or "frozen" not in out or w.snapshot() != before:
        bad.append("a profile in a frozen project: exit %d, want 2 'frozen' and nothing written: %s" % (code, tail(out)))
    return bad


def a_two_servers_one_kind(w):
    bad = made_demo(w)
    if bad:
        return bad
    before = w.snapshot()
    code, out = w.forge("new", "@code", "--sets", "ARCH_SET", "--server", "plain", "--server", "plain-demo", "--apply", cwd=w.project("demo"))
    if code != 2 or "both the kind 'plain'" not in out or w.snapshot() != before:
        bad.append("two servers of one kind: exit %d, want 2 'both the kind' and nothing written: %s" % (code, tail(out)))
    return bad


def a_profile_twice(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", *answered(profiles="code,code", sets="ARCH_SET"), "--apply")
    if code != 2 or "twice" not in out or w.snapshot() != before:
        return ["a profile named twice: exit %d, want 2 'twice' and nothing written: %s" % (code, tail(out))]
    return []


def a_help(w):
    code, out = w.forge("new", "--help")
    text = " ".join(out.split())
    bad = []
    if text.count("replaces the unscoped") < 3:  # --sets, --skills and --server each say it
        bad.append("forge new --help says 'replaces the unscoped' %d time(s), want 3 (--sets, --skills, --server)" % text.count("replaces the unscoped"))
    if "every other question needs its flag" not in text:
        bad.append("forge new --help (--yes) does not say 'every other question needs its flag'")
    return bad


INJECT_PROFILE = (NEW, '            lib.write_text(project_file, lib.dumps(doc) + "\\n", mode="keep")\n',
                  '            raise OSError("injected")\n            lib.write_text(project_file, lib.dumps(doc) + "\\n", mode="keep")\n')
INJECT = (NEW, '            if row or extras:\n', '            raise OSError("injected")\n            if row or extras:\n')
LISTS_BLOCK = '''    if interactive and not lists_answered(flags, scope):  # the two questions, or none of them
        stack_sets = set(ctx.stack["skill_sets"]) if ctx.stack else set()
        rows = [(s, ctx.set_label(s) + (" (the stack's)" if s in stack_sets else ""), False) for s in ctx.sets]
        sets = asker.pick("sets", label + "skills, by sets of similar ones", rows)
        members = {n for s in sets or [] for n in ctx.sets.get(s, [])}
        skills = asker.pick("skills", label + "the final list of skills (the sets' members are on; add and remove)",
                            [(n, n, n in members) for n in ctx.installed])
'''
SERVERS_BLOCK = '''    if servers is None and interactive:
        rows = ctx.server_rows(definition_kinds)
        servers = asker.pick("servers", label + "MCP servers (an account server is <service>-<project>)", [(s, s, False) for s in rows])
'''
KEYBOARD = (NEW, '    except KeyboardInterrupt:\n        return refuse(130, INTERRUPTED)\n    except ask.Cancelled as e:\n        return refuse(1, "%s -- nothing written" % e)\n'
                 '    if bad:\n        return refuse(2, "nothing written, %s" % "; ".join(bad))\n    if rows:',
             '    except ask.Cancelled as e:\n        return refuse(1, "%s -- nothing written" % e)\n'
             '    if bad:\n        return refuse(2, "nothing written, %s" % "; ".join(bad))\n    if rows:')
NO_RESOLVE = (ASK, "    if not problems:\n        check_resolves(ctx, rows, new_defs, problems)\n", "    if False:\n        check_resolves(ctx, rows, new_defs, problems)\n")
HELP_CLI = "forge/cli.py"
CONTROLS = [
    ("servers asked before skills", a_order, [(ASK, LISTS_BLOCK + SERVERS_BLOCK, SERVERS_BLOCK + LISTS_BLOCK)], "order: servers before skills", {}),
    ("the flags' list kept as typed", a_same_by_flags_and_prompts,
     [(ASK, 'return sorted(set(target["skills"]))', 'return list(target["skills"])')], "flags and prompts differ", {}),
    ("the edited list ignored", a_edited_list, [(ASK, '        skills = asker.pick("skills", ', '        _ = asker.pick("skills", ')],
     "edited list did not reach the file", {}),
    ("no definition written", a_profile_here, [(NEW, "    for pname, d in new_defs.items():", "    for pname, d in []:")],
     "forge new @code left no definition", {}),
    ("a reserved word list", a_profile_names, [(NEW, "    why = profiles.name_error(name)\n    if why:\n        return refuse(2, \"%s is not a profile name",
                                                 "    why = profiles.name_error(name) or (\"reserved\" if name == \"list\" else None)\n    if why:\n        return refuse(2, \"%s is not a profile name")],
     "profile named 'list' rejected", {}),
    ("no name check", a_profile_names,
     [(NEW, "    why = profiles.name_error(name)\n    if why:\n        return refuse(2, \"%s is not a profile name", "    why = None\n    if why:\n        return refuse(2, \"%s is not a profile name"),
      (ASK, "        why = profiles.name_error(n)\n        if why:\n", "        why = None\n        if why:\n"),
      (NEW, "    why = lib.project_error(doc)\n    if why:\n        return refuse(2, \"nothing written, the project file would not be valid: %s\" % why)\n    print(\"forge new @",
       "    print(\"forge new @")],
     "profile named '-x' created", {}),
    ("a profile with nothing answered", a_nothing_answered, [NO_RESOLVE], "a profile with nothing was made", {}),
    ("definitions' folder not undone", a_failure_after_write, [INJECT, (NEW, '        undo.append(("dir", folder))\n', "        pass\n")],
     "left behind", {}),
    ("@NAME's rollback taken out", a_profile_failure, [INJECT_PROFILE, (NEW, "        rollback(steps=undo)\n", "        pass\n")], "left behind", {}),
    ("the new-profile row does nothing", a_screen_row, [("forge/configure.py", "                return new_profile(name, prof)", "                return 0")],
     "the new-profile row made no profile", {}),
    ("a plan without the answers", a_plan_shows_answers, [(NEW, "    for line in describe(ctx, ans, rows, new_defs):\n        print(line)\n    print(\"  then",
                                                           "    print(\"  then")],
     "the plan does not show", {}),
    ("a profile that is not resolved", a_resolves, [NO_RESOLVE], "unresolved profile was written", {}),
    ("one answer, the others free", a_partial_answers, [(ASK, "    if given_some and not ask_on:", "    if False:")], "a partial answer", {}),
    ("a stack flag is no answer", a_partial_answers,
     [(ASK, "flags.memory is not None or flags.stack_given())))", "flags.memory is not None)))")], "a stack flag alone", {}),
    ("the own account server taken for another's", a_own_account_server,
     [(ASK, "for o in [project] + list(others) if", "for o in list(others) if")], "the own account server of my-other refused", {}),
    ("the own server is always its own", a_own_account_server,
     [(ASK, "    best = max(named, key=len)\n    return None if best == project else best\n",
       "    if project in named:\n        return None\n    return max(named, key=len)\n")], "taken by a shorter name", {}),
    ("mempalace not a memory", a_memory_mempalace, [(ASK, ', "mempalace": ("mempalace",)}', "}")], "--memory mempalace: servers", {"mempalace": True}),
    ("the memory servers not kept out of the rows", a_memory_mempalace,
     [(ASK, "        return {s for servers in MEMORY.values() for s in servers}", "        return set()")], "asked: servers", {"mempalace": True}),
    ("memory off not said", a_stack_and_memory, [(ASK, "    elif not lib.on(ans.memory):", "    elif False:")], "with the integration off", {}),
    ("two memory backends", a_one_backend, [(ASK, "    check_one_backend(ans, problems)\n", "    pass\n")], "two memory backends", {"mempalace": True}),
    ("set_docs not checked", a_set_docs_type, [(ASK, "        elif not isinstance(self.docs, dict):", "        elif False:")], "set_docs 'oops'", {}),
    ("Ctrl-C at the profiles question", a_ctrl_c, [KEYBOARD], "Ctrl-C at the profiles question", {}),
    ("Ctrl-C at the new profile's name", a_ctrl_c,
     [("forge/configure.py", '    except KeyboardInterrupt:\n        _say("forge config: interrupted (Ctrl-C), nothing was written", err=True)\n        return 130\n', "")],
     "Ctrl-C at the name of the new profile", {}),
    ("--sets alone asks the final list", a_sets_alone,
     [(ASK, "    return flags.of(flags.sets, scope) is not None or flags.of(flags.skills, scope) is not None\n",
       "    return flags.of(flags.sets, scope) is not None and flags.of(flags.skills, scope) is not None\n")], "--sets alone in a terminal", {}),
    ("the stack question always asked", a_stack_question,
     [(ASK, "        if ask_on and not given_all and not flags.stack_given():", "        if ask_on and not flags.stack_given():")],
     "every answer by flag: asked", {}),
    ("the memory answer left out of given_all", a_stack_question,
     [(ASK, "given_all = (flags.profiles is not None and flags.memory is not None and all(", "given_all = (flags.profiles is not None and all(")],
     "memory unanswered: asked", {}),
    ("scoping ignored", a_scoped, [(ASK, "        return table[scope] if scope in table else table.get(None)", "        return table.get(None)")],
     "scoped sets: profiles", {}),
    ("a scoped value added to the unscoped one", a_scoped,
     [(ASK, "        return table[scope] if scope in table else table.get(None)",
       "        return (table[scope] + (table.get(None) or [])) if scope in table else table.get(None)")], "scoped sets: profiles", {}),
    ("n at make it writes", a_confirm_no, [(NEW, '    print("nothing written")\n    return False', '    print("nothing written")\n    return True')],
     "n at make it", {}),
    ("a frozen project accepted", a_frozen, [(NEW, '    if doc.get("frozen"):\n        return refuse(2,', '    if False:\n        return refuse(2,')],
     "a profile in a frozen project", {}),
    ("two servers of one kind", a_two_servers_one_kind, [(ASK, "            if kind in assigned:\n", "            if False:\n")],
     "two servers of one kind", {}),
    ("a profile named twice", a_profile_twice, [(ASK, "    if len(set(ans.profiles)) != len(ans.profiles):\n", "    if False:\n")],
     "a profile named twice", {}),
    ("the scoping help gone", a_help, [(HELP_CLI, "A scoped value replaces the unscoped one for that profile; it does not add to it",
                                       "A scoped value is for that profile")], "'replaces the unscoped'", {}),
    ("the --yes help gone", a_help, [(HELP_CLI, "with one, every other question needs its flag", "with one, the others are free")],
     "every other question needs its flag", {}),
]
PLAIN = [("order", a_order, {}), ("flags and prompts", a_same_by_flags_and_prompts, {}), ("edited list", a_edited_list, {}),
         ("profile here", a_profile_here, {}), ("profile names", a_profile_names, {}), ("nothing answered", a_nothing_answered, {}),
         ("failure after the first write", a_failure_after_write, {"mutate": [INJECT]}), ("profile failure", a_profile_failure, {"mutate": [INJECT_PROFILE]}), ("screen row", a_screen_row, {}), ("plan", a_plan_shows_answers, {}),
         ("stack and memory", a_stack_and_memory, {}), ("memory hindsight", a_memory_hindsight, {"hindsight": True}),
         ("cancelled", a_cancelled, {}), ("partial answers", a_partial_answers, {}), ("resolves", a_resolves, {}),
         ("own account server", a_own_account_server, {}), ("memory mempalace", a_memory_mempalace, {"mempalace": True}),
         ("one backend", a_one_backend, {"mempalace": True}), ("set_docs type", a_set_docs_type, {}), ("ctrl-c", a_ctrl_c, {}),
         ("sets alone", a_sets_alone, {}), ("stack question", a_stack_question, {}), ("scoped", a_scoped, {}),
         ("confirm no", a_confirm_no, {}), ("frozen", a_frozen, {}), ("two servers one kind", a_two_servers_one_kind, {}),
         ("profile twice", a_profile_twice, {}), ("help", a_help, {})]


def world(tag, mutate=(), hindsight=False, mempalace=False):
    w = World(tag, mutate=mutate)
    prep(w, hindsight=hindsight, mempalace=mempalace)
    return w


def main():
    only = [t for t in os.environ.get("ASK_ONLY", "").split(",") if t]  # a subset while working: labels (or parts of them); a full run has none
    for label, fn, kw in PLAIN:
        if only and not any(t in label for t in only):
            continue
        w = world("ask", mutate=kw.get("mutate", ()), hindsight=kw.get("hindsight", False), mempalace=kw.get("mempalace", False))
        try:
            for why in fn(w):
                failures.append("%s -- %s" % (label, why))
            n_checks[0] += 1
        finally:
            w.close()
    for label, fn, mutate, needle, kw in CONTROLS:
        if only and not any(t in label for t in only):
            continue
        cw = world("askc", mutate=mutate, hindsight=kw.get("hindsight", False), mempalace=kw.get("mempalace", False))
        try:
            got = cw.anchors_missing or fn(cw)
            test_new.check("control '%s' produces %r" % (label, needle), any(needle in g for g in got), "got %s" % (got[:2] or "no failure (the assertion passed)"))
            shown = [g for g in got if needle in g] or got
            print("control %-40s -> %s" % (label, (shown[0] if shown else "NOT SEEN FAILING")[:110]))
        finally:
            cw.close()
    failures.extend(test_new.failures)
    n = n_checks[0] + test_new.n_checks[0]
    sandbox.cleanup()
    if failures:
        print("%d check(s), %d failure(s)" % (n, len(failures)))
        for f in failures:
            print("FAIL %s" % f)
        sys.exit(1)
    print("%d check(s), 0 failures" % n)


if __name__ == "__main__":
    main()
