#!/usr/bin/env python3
"""The project is an argument, not a flag: `forge sync [NAME | --all] [--apply]` and `forge uninstall [NAME |
--integration N] [--apply]`, like `doctor`, `metrics` and `log`. `--project NAME` is cut, not aliased: it exits 2 with one
line on stderr naming the new form (`forge sync --project toy: now 'forge sync toy'`), the same way the renamed commands
of tests/test_command_grammar.py refuse their old names, and runs nothing. `forge sync NAME` with a name no project has
refuses (exit 1, the known names) and runs no generator: a misspelled name must never fall through to "everything".
`cmd_sync` still hands `--project NAME` to the generators of scripts/sync/ (they are machine scripts, not commands).

The world is test_journal's: W/forge (an engine-only copy), W/home, W/projects/toy-a and toy-b, every integration off.
GRAMMAR_DUMP=DIR also writes the dry-runs of `forge sync` and `forge doctor` there, the world's path masked as W, so a run
on the base and a run after can be compared with `cmp` (the dry-runs must not change).

Seen failing on 5f69899 (the old flags only): "(a) sync --project toy-a: (exit, 'forge sync toy-a' in output): got
(0, False), want (2, True)", "(b) sync toy-a: exit: got 2, want 0" (`forge: error: unrecognized arguments: toy-a`),
"(c) uninstall --project toy-a: (exit, 'forge uninstall toy-a' in output): got (1, False), want (2, True)" and "(b) sync
nope: refused, exit: got 2, want 1" (unrecognized arguments); 22 of 34 checks FAILED.
Negative controls, each a throwaway edit of forge/cli.py (a copy of it put back after):
  (a) the refusal removed and `--project` put back as an option of both parsers: "(a) sync --project toy-a: (exit, 'forge
      sync toy-a' in output) -- got (0, False): ... ; old --project accepted" (and the same for --project=toy-a and
      --apply --project toy-a, and for uninstall: "(c) uninstall --project toy-a: ... got (0, False): old --project accepted"
      is checked by the same mutant);
  (b) cmd_sync ignoring NAME and passing `--all`: "(b) synced other projects: toy-b has no generated file -- toy-b has
      ['.claude/AGENT-SYSTEM.md', '.claude/settings.local.json', 'AGENTS.md', 'CLAUDE.md']";
  unknown name: cmd_sync without its project lookup: "(b) sync nope: no generator ran -- forge sync: failed -- agent config,
      system doc | forge: unknown project: nope (known: toy-a, toy-b)" (the two generators that check refuse it, the others
      ran: the lookup is what makes it one clean line and no run);
  (c) cmd_uninstall dropping NAME: "(c) uninstalled other projects: toy-b's settings.local.json is gone -- toy-b changed", and
      "(c) uninstall toy-a of a live project: refused, exit 1, nothing removed -- got 0".
The mutations are not kept."""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402

failures, n_checks = [], [0]


def check(label, ok, detail=""):
    n_checks[0] += 1
    if not ok:
        failures.append("%s -- %s" % (label, detail))
        print("FAIL", label, "--", detail)


def tail(text, n=4):
    return " | ".join(text.strip().splitlines()[-n:])


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


top = sandbox.mkdtemp("grammar-test-")
try:
    root, home, tmp = (os.path.join(top, d) for d in ("forge", "home", "tmp"))
    projects = {n: os.path.join(top, "projects", n) for n in ("toy-a", "toy-b")}
    for d in [home, tmp] + list(projects.values()):
        os.makedirs(d)
    sandbox.copy_engine(root)
    sandbox.seed(root)
    sandbox.git(root, "init", "-q")
    sandbox.git(root, "add", "-A")
    sandbox.git(root, "commit", "-q", "-m", "engine")

    cfg = os.path.join(root, "config")
    fj = json.load(open(os.path.join(cfg, "forge.json")))
    fj["integrations"] = {n: False for n in fj["integrations"]}
    fj["codex_harness"] = False
    write_json(os.path.join(cfg, "forge.json"), fj)
    for f in os.listdir(os.path.join(cfg, "projects")):  # the fixture's projects name /srv/toy/*, outside the world
        os.remove(os.path.join(cfg, "projects", f))
    for name in projects:
        write_json(os.path.join(cfg, "projects", name + ".claude.json"),
                   {"project": name, "project_path": projects[name], "enableAllProjectMcpServers": True, "servers": [],
                    "env": {"PLAIN": "1"}, "plugins_keep": [], "skills_keep": ["*"], "permissions": {}})
    write_json(os.path.join(root, "credentials", "secrets.json"), {})
    os.symlink(os.path.join("..", "credentials", "secrets.json"), os.path.join(cfg, "secrets.json"))

    ENV = sandbox.bare_env(home, tmp)

    def forge(*args):
        r = subprocess.run([sys.executable, os.path.join(root, "bin", "forge")] + list(args), cwd=root, env=ENV,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
        return r.returncode, r.stdout + r.stderr

    def tree(name):
        """{relative path: bytes} of everything under one project's directory."""
        out = {}
        for d, _, files in os.walk(projects[name]):
            if os.sep + ".git" in d + os.sep:
                continue
            for f in files:
                p = os.path.join(d, f)
                out[os.path.relpath(p, projects[name])] = open(p, "rb").read() if os.path.isfile(p) else b""
        return out

    def tree_of(d):
        out = {}
        for dd, _, files in os.walk(d):
            for f in files:
                p = os.path.join(dd, f)
                out[os.path.relpath(p, d)] = open(p, "rb").read() if os.path.isfile(p) else b""
        return out

    def slp(name):
        return os.path.join(projects[name], ".claude", "settings.local.json")

    dump = os.environ.get("GRAMMAR_DUMP")
    if dump:
        os.makedirs(dump, exist_ok=True)
        for label, args in (("sync", ["sync"]), ("doctor", ["doctor"])):
            code, out = forge(*args)
            with open(os.path.join(dump, label + ".txt"), "w", encoding="utf-8") as fh:
                fh.write("exit %d\n%s" % (code, out.replace(top, "W")))

    # ---------------------------------------------------------------- sync
    # (a) the old flag is refused, one line naming the new form, and nothing ran.
    for args, name in ((["--project", "toy-a"], "toy-a"), (["--project=toy-a"], "toy-a"), (["--apply", "--project", "toy-a"], "toy-a"),
                       (["toy-a", "--project", "toy-b"], "toy-b")):
        code, out = forge("sync", *args)
        want = "forge sync %s" % name
        check("(a) sync %s: (exit, '%s' in output)" % (" ".join(args), want), (code, want in out) == (2, True),
              "got (%d, %s): %s" % (code, want in out, tail(out)) + ("; old --project accepted" if code == 0 else ""))
        check("(a) sync %s: nothing ran" % " ".join(args), "== forge:" not in out, tail(out))
    code, out = forge("sync", "--project")
    check("(a) sync --project with no value: exit 2 and says 'forge sync NAME'", code == 2 and "forge sync NAME" in out, tail(out))
    check("(a) the refusals wrote nothing", not os.path.exists(slp("toy-a")) and not os.path.exists(slp("toy-b")))

    # (b) a name scopes the run to that project; the same writes as the full sync makes for it, and nothing of another's.
    code, out = forge("sync", "toy-a", "--apply")
    check("(b) sync toy-a --apply: exit", code == 0, "got %d: %s" % (code, tail(out)))
    check("(b) toy-a has its settings.local.json (else nothing was looked at)", os.path.isfile(slp("toy-a")), "missing %s" % slp("toy-a"))
    check("(b) synced other projects: toy-b has no generated file", not tree("toy-b"), "toy-b has %s" % sorted(tree("toy-b"))[:4])
    scoped = tree("toy-a")
    code, out = forge("sync", "--apply", "toy-a")
    check("(b) sync --apply toy-a (the other order): exit 0 and byte-identical", code == 0 and tree("toy-a") == scoped, tail(out))
    code, out = forge("sync", "--all", "--apply")
    check("(b) sync --all --apply: exit", code == 0, "got %d: %s" % (code, tail(out)))
    check("(b) the full sync writes toy-b too (control: the two projects differ in what they have)", os.path.isfile(slp("toy-b")))
    check("(b) toy-a's tree after sync NAME equals its tree after sync --all", tree("toy-a") == scoped,
          "differs: %s" % sorted(k for k in set(scoped) | set(tree("toy-a")) if scoped.get(k) != tree("toy-a").get(k))[:4])
    # The dry-run starts from a pending change (a generated file gone), or it proves nothing: with nothing to do an apply
    # writes nothing either. Seen passing with cmd_sync passing apply=True to run_steps (59 checks ok on 515ed40); now red:
    # "(b) a dry-run of sync toy-a: writes nothing -- the dry-run wrote <W>/projects/toy-a/.claude/settings.local.json" and
    # "... names the project's generators and the pending change -- got 0: = toy-a up to date | 0 change(s) applied.".
    os.remove(slp("toy-a"))
    code, out = forge("sync", "toy-a")
    check("(b) a dry-run of sync toy-a: exit 0, names the project's generators and the pending change",
          code == 0 and "== forge:" in out and "toy-a" in out and "change(s) would apply" in out, "got %d: %s" % (code, tail(out)))
    check("(b) a dry-run of sync toy-a: writes nothing", not os.path.exists(slp("toy-a")), "the dry-run wrote %s" % slp("toy-a"))
    code, out = forge("sync", "toy-a", "--apply")
    check("(b) sync toy-a --apply repairs it: exit 0 and byte-identical to before", code == 0 and tree("toy-a") == scoped, tail(out))

    # unknown name: refused, no generator runs (it must not fall through to "everything").
    before = {n: tree(n) for n in projects}
    for apply in ([], ["--apply"]):
        code, out = forge("sync", "nope", *apply)
        check("(b) sync nope %s: refused, exit: got %d, want 1" % (" ".join(apply), code), code == 1, tail(out))
        check("(b) sync nope: says unknown project and the known names",
              "unknown project: nope" in out and "toy-a" in out and "toy-b" in out, tail(out))
        check("(b) sync nope: no generator ran", "== forge:" not in out, tail(out))
    check("(b) sync nope wrote nothing", {n: tree(n) for n in projects} == before)
    code, out = forge("sync", "toy-a", "--all")
    check("(b) sync toy-a --all: argparse refuses, exit 2", code == 2, tail(out))

    # an empty name is an unset variable (`forge sync "$NAME"`), never "no name": refused before anything runs.
    # Red on 76b3519: `sync "" --apply` equals `sync --all --apply` (toy-b's deleted settings.local.json is back) and
    # `uninstall "" --apply` strips every project: "(e) sync '' --apply: nothing changed -- changed: ['home', 'toy-b']" and
    # "(e) uninstall '' --apply: nothing changed -- changed: ['home', 'toy-a', 'toy-b']". Control: with the check removed
    # the same two lines come back.
    os.remove(slp("toy-b"))  # a stale project: a whole sync would regenerate it, a refused one leaves it missing
    for empty in ("", "  "):
        for cmd, more in (("sync", ["--apply"]), ("uninstall", ["--apply"]), ("sync", []), ("uninstall", [])):
            snap = {n: tree(n) for n in projects}, tree_of(home)
            code, out = forge(cmd, empty, *more)
            now = {n: tree(n) for n in projects}, tree_of(home)
            label = "(e) %s %r %s" % (cmd, empty, " ".join(more))
            check(label + ": exit 2 and one line naming the two forms", code == 2 and "empty" in out and
                  ("forge sync NAME" in out and "forge sync --all" in out if cmd == "sync" else
                   "forge uninstall NAME" in out and "forge uninstall --integration" in out), "got %d: %s" % (code, tail(out)))
            check(label + ": nothing ran", "== forge:" not in out and "looked at" not in out, tail(out))
            check(label + ": nothing changed", snap == now, "changed: %s" % sorted(
                [n for n in projects if snap[0][n] != now[0][n]] + (["home"] if snap[1] != now[1] else [])))
    check("(e) the refused sync left toy-b's settings.local.json missing (it would regenerate it)", not os.path.exists(slp("toy-b")))
    forge("sync", "--all", "--apply")  # put it back for what follows

    # ------------------------------------------------------------- uninstall
    code, out = forge("uninstall", "--project", "toy-a")
    check("(c) uninstall --project toy-a: (exit, 'forge uninstall toy-a' in output)", (code, "forge uninstall toy-a" in out) == (2, True),
          "got (%d, %s): %s" % (code, "forge uninstall toy-a" in out, tail(out)) + ("; old --project accepted" if code != 2 else ""))
    code, out = forge("uninstall", "--project=toy-a", "--apply")
    check("(c) uninstall --project=toy-a --apply: exit 2 and nothing removed",
          code == 2 and os.path.isfile(slp("toy-a")) and os.path.isfile(slp("toy-b")), tail(out))
    # a live project is refused by uninstall itself (its own rule), through the new form too
    code, out = forge("uninstall", "toy-a", "--apply")
    check("(c) uninstall toy-a of a live project: refused, exit 1, nothing removed",
          code == 1 and "!" in out and os.path.isfile(slp("toy-a")), "got %d: %s" % (code, tail(out)))
    pf = os.path.join(cfg, "projects", "toy-a.claude.json")
    prof = json.load(open(pf))
    prof["frozen"] = True
    write_json(pf, prof)
    b_before = tree("toy-b")
    code, out = forge("uninstall", "toy-a")
    check("(c) uninstall toy-a (frozen) dry-run: exit 0 and removes nothing", code == 0 and os.path.isfile(slp("toy-a")), "got %d: %s" % (code, tail(out)))
    code, out = forge("uninstall", "toy-a", "--apply")
    check("(c) uninstall toy-a --apply: exit", code == 0, "got %d: %s" % (code, tail(out)))
    check("(c) toy-a's settings.local.json is gone (else nothing was looked at)", not os.path.exists(slp("toy-a")), "still there")
    check("(c) uninstalled other projects: toy-b's settings.local.json is gone", os.path.isfile(slp("toy-b")) and tree("toy-b") == b_before,
          "toy-b changed")
    code, out = forge("uninstall", "toy-a", "--integration", "codex")
    check("(c) uninstall toy-a --integration codex: argparse refuses, exit 2", code == 2, tail(out))
finally:
    sandbox.cleanup(failed=bool(failures))

if failures:
    print("%d of %d checks FAILED" % (len(failures), n_checks[0]))
    sys.exit(1)
print("ok: %d checks" % n_checks[0])
