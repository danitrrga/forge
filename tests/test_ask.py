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
DRIVER = '''import json, sys
sys.path.insert(0, sys.argv[1])
from forge import ask, cli
spec = json.load(open(sys.argv[2]))
made = []
def make():
    asker = ask.Asker(keys=spec["keys"], lines=spec["lines"], interactive=True)
    made.append(asker)
    return asker
ask.make_asker = make
code = cli.main(spec["argv"])
print("ASKED " + json.dumps(made[-1].asked if made else []))
sys.exit(code)
'''
ORDER = ["profiles", "sets", "skills", "servers", "memory", "stack"]


def write_json(path, doc):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def prep(w, hindsight=False):
    """The world's skills, sets, registry and a second project; hindsight on only where a test asks (a sync then cannot finish)."""
    for n in ("alpha", "beta", "gamma", "delta"):
        os.makedirs(os.path.join(w.home, ".claude", "skills", n))
        with open(os.path.join(w.home, ".claude", "skills", n, "SKILL.md"), "w") as fh:
            fh.write("---\nname: %s\ndescription: toy\n---\n" % n)
    path = w.path("config", "forge.json")
    doc = test_new.read_json(path)
    doc["skill_keep"]["sets"] = {"ARCH_SET": ["alpha", "beta"], "OTHER_SET": ["gamma"]}
    doc["skill_keep"]["set_docs"] = {"ARCH_SET": "architecture skills"}
    doc["integrations"]["hindsight"] = hindsight
    write_json(path, doc)
    stdio = {"type": "stdio", "command": "true", "args": []}
    write_json(w.path("config", "mcp-registry.json"), {"servers": {n: dict(stdio) for n in (
        "analytics-demo", "analytics-other", "plain", "hindsight-coding-agents", "hindsight-recall")}})
    other = os.path.join(w.top, "other")
    os.makedirs(other)
    write_json(w.path("config", "projects", "other.claude.json"), {"project": "other", "project_path": other,
                                                                 "writes_tracked_files": False, "servers": []})


def write_driver(w):
    d = os.path.join(w.top, "driver")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "driver.py"), "w") as fh:
        fh.write(DRIVER)
    write_json(os.path.join(d, "spec.json"), {})
    return d


def asked_run(w, argv, keys, lines):
    """(exit code, output, the questions asked) of `forge argv` with the owner's recorded answers."""
    d = write_driver(w)
    write_json(os.path.join(d, "spec.json"), {"argv": argv, "keys": keys, "lines": lines})
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
    code, out = w.forge("new", "@list", "--sets", "OTHER_SET", "--apply", cwd=w.project("demo"))
    if code != 0 or "list" not in ((project_doc(w) or {}).get("profiles") or {}).get("offered", {}):
        bad.append("profile named 'list' rejected: exit %d: %s" % (code, tail(out)))
    before = w.snapshot()
    for arg, reason in (("@-x", "starts with -"), ("@@x", "starts with @"), ("@Bad", "kebab-case"), ("@default", "label")):
        code, out = w.forge("new", arg, "--sets", "OTHER_SET", "--apply", cwd=w.project("demo"))
        if code != 2 or reason not in out:
            bad.append("profile named '%s' created or refused without the reason %r: exit %d: %s" % (arg[1:], reason, code, tail(out)))
    if w.snapshot() != before:
        bad.append("a refused profile name wrote: %s" % test_new.changed(before, w.snapshot())[:4])
    return bad


def a_nothing_answered(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--profiles", "code,docs", "--apply")
    bad = []
    if code != 2 or "@code" not in out or "@docs" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("a profile with nothing was made or not named in one error: exit %d: %s" % (code, tail(out)))
    if w.snapshot() != before or os.path.lexists(w.project("demo")):
        bad.append("a profile with nothing was made: it wrote %s" % test_new.changed(before, w.snapshot())[:4])
    # --stack missing and an answer missing: one error naming both
    code, out = w.forge("new", "demo", "--profiles", "code", "--apply")
    if code != 2 or "--stack" not in out or "@code" not in out or len([l for l in out.splitlines() if l.strip()]) != 1:
        bad.append("--stack and the profile's answer not named together: exit %d: %s" % (code, tail(out)))
    return bad


def a_failure_after_write(w):
    before = w.snapshot()
    code, out = w.forge("new", "demo", "--stack", "generic", "--profiles", "code", "--sets", "ARCH_SET", "--apply")
    bad = []
    if code != 1 or "injected" not in out:
        bad.append("the injected failure did not stop the run: exit %d: %s" % (code, tail(out)))
    after = w.snapshot()
    if after != before:
        bad.append("left behind: %s" % ", ".join(test_new.left_behind(before, after)[:6]))
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
    code, out = w.forge("new", "demo", "--stack", "next", "--check", "pnpm nope", "--plugin", "nope@x", "--memory", "mempalace")
    for needle in ("pnpm nope", "nope@x", "mempalace"):
        if code != 2 or needle not in out:
            bad.append("a wrong %s: exit %d: %s" % (needle, code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", "--memory", "hindsight")
    if code != 2 or "off in config/forge.json" not in out:
        bad.append("--memory hindsight with the integration off: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", "--server", "analytics-other")
    if code != 2 or "account server of project other" not in out:
        bad.append("another project's account server: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", "--sets", "NOPE")
    if code != 2 or "NOPE" not in out:
        bad.append("an unknown set: exit %d: %s" % (code, tail(out)))
    code, out = w.forge("new", "demo", "--stack", "next", "--sets", "@code:ARCH_SET")
    if code != 2 or "not one of the profiles" not in out:
        bad.append("a scope that names no profile: exit %d: %s" % (code, tail(out)))
    return bad


def a_memory_hindsight(w):
    """Hindsight on: the memory servers reach the project file (the sync that follows cannot finish in a toy world, so the exit is not 0)."""
    code, out = w.forge("new", "demo", "--stack", "generic", "--memory", "hindsight", "--apply")
    doc = project_doc(w) or {}
    if doc.get("servers") != ["hindsight-coding-agents", "hindsight-recall"]:
        return ["--memory hindsight left servers %s: exit %d: %s" % (doc.get("servers"), code, tail(out))]
    return []


def a_cancelled(w):
    def forge_only(snap):  # the driver and its spec are the test's own files, not something forge wrote
        return {k: v for k, v in snap.items() if not k.startswith("driver")}
    before = forge_only(w.snapshot())
    code, out, asked = asked_run(w, ["new", "demo", "--stack", "generic", "--apply"], [["esc"]], ["code"])
    if code != 1 or "cancelled" not in out or forge_only(w.snapshot()) != before:
        return ["Esc at a question: exit %d, want 1 'cancelled' and nothing written: %s" % (code, tail(out))]
    return []


INJECT = (NEW, '            if row or extras:\n', '            raise OSError("injected")\n            if row or extras:\n')
SKILLS_BLOCK = '''    if skills is None and interactive:
        members = {n for s in sets or [] for n in ctx.sets.get(s, [])}
        skills = asker.pick("skills", label + "the final list of skills (the sets' members are on; add and remove)",
                            [(n, n, n in members) for n in ctx.installed])
'''
SERVERS_BLOCK = '''    if servers is None and interactive:
        rows = ctx.server_rows(definition_kinds)
        servers = asker.pick("servers", label + "MCP servers (an account server is <service>-<project>)", [(s, s, False) for s in rows])
'''
CONTROLS = [
    ("servers asked before skills", a_order, [(ASK, SKILLS_BLOCK + SERVERS_BLOCK, SERVERS_BLOCK + SKILLS_BLOCK)], "order: servers before skills", {}),
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
    ("a profile with nothing answered", a_nothing_answered, [(ASK, "            if not row:\n", "            if False:\n")],
     "a profile with nothing was made", {}),
    ("definitions' folder not undone", a_failure_after_write, [INJECT, (NEW, '        undo.append(("dir", folder))\n', "        pass\n")],
     "left behind", {}),
    ("a plan without the answers", a_plan_shows_answers, [(NEW, "    for line in describe(ctx, ans, rows, new_defs):\n        print(line)\n    print(\"  then",
                                                           "    print(\"  then")],
     "the plan does not show", {}),
]
PLAIN = [("order", a_order, {}), ("flags and prompts", a_same_by_flags_and_prompts, {}), ("edited list", a_edited_list, {}),
         ("profile here", a_profile_here, {}), ("profile names", a_profile_names, {}), ("nothing answered", a_nothing_answered, {}),
         ("failure after the first write", a_failure_after_write, {"mutate": [INJECT]}), ("plan", a_plan_shows_answers, {}),
         ("stack and memory", a_stack_and_memory, {}), ("memory hindsight", a_memory_hindsight, {"hindsight": True}),
         ("cancelled", a_cancelled, {})]


def world(tag, mutate=(), hindsight=False):
    w = World(tag, mutate=mutate)
    prep(w, hindsight=hindsight)
    return w


def main():
    for label, fn, kw in PLAIN:
        w = world("ask", mutate=kw.get("mutate", ()), hindsight=kw.get("hindsight", False))
        try:
            for why in fn(w):
                failures.append("%s -- %s" % (label, why))
            n_checks[0] += 1
        finally:
            w.close()
    for label, fn, mutate, needle, kw in CONTROLS:
        cw = world("askc", mutate=mutate, hindsight=kw.get("hindsight", False))
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
