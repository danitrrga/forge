#!/usr/bin/env python3
"""Profiles inside a project (forge/profiles.py): a project file may declare `profiles`, forge resolves one into its lists
without writing, `forge list @` lists a project's profiles and `forge list @NAME` shows one. A project without `profiles`
behaves as before, byte for byte.

The world is a toy (tests/sandbox.py): an engine copy, a toy HOME holding the skills `toy-common`, `toy-a`, `toy-b`, `toy-c`,
the project `multi` with two profiles (`toy-b` and `list`, a name that used to be reserved), `errs` with one profile per way
a resolution fails, `none` without `profiles`, `frozen-p`, and definitions under config/profile-defs/. Every command runs
the copy's bin/forge from inside a project directory, with only the toy HOME's environment.

Cases (the plan's control list of 4.3 U3, `show` read as `list @NAME`):
  a  the generator ignores `profiles`: the dry-run of `forge sync --all`, the files `forge sync --apply` writes and `forge
     doctor` are the same for projects with and without the field. (That a project without it is what the branch point gave
     is the cmp of the pull request's description, run once against master; history changes, so no test pins it.)
  b  a definition with an `@SET` and a project row resolves to the expected lists.
  c  an unknown `@SET`, a skill that is not installed, a server kind with no server, a server for a kind the definition does
     not list and a definition that does not exist are each exit 2 naming the profile and the cause.
  d  a malformed `profiles` makes lib.projects() leave the project out and name it.
  e  a profile called `list` is valid and `forge list @list` shows it; `@x`, `-x`, `Big`, a repeated default are refused with
     the reason.
  f  `forge list @`: exit 0 with the profiles, text and --json; no `profiles` is exit 1 saying `no profiles` and `[]`; frozen
     is exit 1; a linked worktree is its main checkout's project; a folder that is no project is exit 2.
  g  `forge list @NAME`: the card and its difference with the default (--json says the same); an unknown name is exit 2 with
     the closest one and the list.
  h  `forge list @ --names`: the names, one per line, no `@`.
  and: none of it writes a file in the world.

Written first, run against the code that had forge/profiles.py and forge/suggest.py but no `list` subcommand and no
`profiles` row in lib: 47 FAIL, among them "b: toy-b resolves to the expected lists -- got None (usage: forge [-h] ... forge:
error: argument cmd: invalid choice: 'list', maybe you meant 'lint'?", "d: a profiles that is not an object is refused --
accepted" and "e: profile named '@x' is refused with the reason -- ... accepted"; case a passed, as it should.
Negative controls, each a mutation made by hand, run once and not kept (the first message each produced):
  a  the generator's loop (forge/sync.py) adding a key to a project that has `profiles` -> "FAIL a: a project with `profiles`
     generates the same as one without -- output of doctor differs; projects/app/.claude/settings.local.json differs; ...".
     The case also carries its own control, a world with that mutation in its engine copy, which must differ from the plain one
     ("a: the control ... is seen"); aimed first at lib.projects(), which sync.py bypasses, it turned red with
     "projects/app/.claude/settings.local.json did not differ: the comparison cannot fail ([])".
  b  resolve() without the `@SET` expansion -> "FAIL b: toy-b resolves to the expected lists -- got None (forge list: profile
     'toy-b' of project 'multi': unknown skill '@TOYSET' (no folder of that name in ~/.claude/skills)"
  c  the server-kind check taken out -> "FAIL c: err-kind is exit 2 -- exit 1, stderr 'Traceback (most recent call last): ..."
  d  project_error not asking profiles.shape_error -> "FAIL d: an offered that is a list is refused -- accepted"
  e  name_error keeping the old reserved words -> "FAIL e: a profile named 'list' is valid (and 'shim') -- profile named 'list'
     rejected: profiles.offered: 'list' is reserved"; accepting a name that starts with @ -> "FAIL e: profile named '@x' is
     refused with the reason -- profile named '@x' accepted or the reason is missing: None"
  f  _list() exiting 0 with no rows -> "FAIL f: no profiles is exit 1 -- list @ exits 0 with no profiles"
  g  suggest.message() without the suggestion -> "FAIL g: @toy- proposes @toy-b -- no suggestion in: forge list: no profile
     '@toy-' in project 'multi'. There are: @code, @list, @toy-b"
  h  --names printing "@" + name -> "FAIL h: no @ in the --names output -- @ in --names output: '@code, @toy-b, @list, one per line'"
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import sandbox  # noqa: E402
from forge import lib, profiles, suggest  # noqa: E402

failures = []
SKILLS = ("toy-common", "toy-a", "toy-b", "toy-c")


def check(name, ok, detail=""):
    if not ok:
        failures.append(name)
        print("FAIL %s -- %s" % (name, detail))


def write_json(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


DEFS = {
    "toy-b": {"description": "toy B", "color": "red", "skills": ["@TOYSET"], "plugins": ["p-def@m"], "server_kinds": ["analytics"],
              "permissions": {"allow": ["Read"]}, "env": {"TOY_B": "1"}},
    "list": {"description": "named like the command", "color": "blue", "skills": ["toy-a"]},
    "err-set": {"skills": ["@NOPE"]},
    "err-skill": {"skills": ["toy-missing"]},
    "err-kind": {"server_kinds": ["analytics", "search"]},
    "err-extra": {"server_kinds": ["analytics"]},
}
DEFS["from-example"] = read_json(os.path.join(ROOT, "examples", "profile-def.json"))  # the shape a stranger copies
ERRS_ROWS = {"from-example": {}, "err-set": {}, "err-skill": {}, "err-kind": {"servers": {"analytics": "toy-echo"}},
             "err-extra": {"servers": {"analytics": "toy-echo", "search": "toy-echo"}}, "err-nodef": {}}
PROJECTS = {
    "multi": {"skills_keep": ["toy-common", "toy-a"], "plugins_keep": ["p-def@m"], "servers": [], "env": {"TOY": "1"},
              "profiles": {"default": "code", "offered": {
                  "toy-b": {"skills": ["toy-c"], "plugins": ["toy-plugin@x"], "servers": {"analytics": "toy-echo"}},
                  "list": {}}}},
    "errs": {"profiles": {"default": "code", "offered": ERRS_ROWS}},
    "none": {"skills_keep": ["toy-common"]},
    "frozen-p": {"frozen": True, "profiles": {"default": "code", "offered": {"list": {}}}},
    "bad": {"profiles": 5},
}


class World:
    """An engine copy, a toy HOME and the projects `names`; `extra` is added to each project file, `mutate` is one text
    replacement (file, old, new) in the copy."""

    def __init__(self, names, extra=None, mutate=None):
        self.root = sandbox.mkdtemp("forge-prof-")
        self.forge, self.home = os.path.join(self.root, "forge"), os.path.join(self.root, "home")
        sandbox.copy_engine(self.forge)
        sandbox.seed(self.forge)
        if mutate:
            rel, old, new = mutate
            p = os.path.join(self.forge, rel)
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            assert text.count(old) == 1, "the control's anchor is not in %s" % rel
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
        for s in SKILLS:
            os.makedirs(os.path.join(self.home, ".claude", "skills", s))
        cfg = os.path.join(self.forge, "config")
        doc = read_json(os.path.join(cfg, "forge.json"))
        doc["integrations"] = {}
        doc.pop("codex_harness", None)
        doc["skill_keep"]["sets"] = {"TOYSET": ["toy-a", "toy-b"]}
        write_json(os.path.join(cfg, "forge.json"), doc)
        for f in os.listdir(os.path.join(cfg, "projects")):
            os.remove(os.path.join(cfg, "projects", f))
        for name in names:
            body = dict(PROJECTS.get(name, {"skills_keep": ["toy-common"]}), project=name, project_path=self.pp(name), **(extra or {}))
            write_json(os.path.join(cfg, "projects", name + ".claude.json"), body)
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

    def pp(self, name):
        return os.path.join(self.root, "projects", name)

    def forge_cmd(self, args, cwd=None):
        """(exit code, stdout, stderr) of bin/forge `args` run from `cwd` (default: the forge copy)."""
        r = subprocess.run([sys.executable, os.path.join(self.forge, "bin", "forge")] + list(args), cwd=cwd or self.forge,
                           env=sandbox.bare_env(self.home, self.root), capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode, r.stdout.replace(self.root, "@S@"), r.stderr.replace(self.root, "@S@")

    def files(self, sub):
        out = {}
        for d, _, names in os.walk(os.path.join(self.root, sub)):
            for n in names:
                p = os.path.join(d, n)
                if os.path.isfile(p) and not os.path.islink(p) and os.sep + ".git" + os.sep not in p:
                    with open(p, "rb") as fh:
                        out[os.path.relpath(p, self.root)] = fh.read().replace(self.root.encode(), b"@S@")
        return out


def case_a():
    """The generator ignores `profiles`: the same projects, with and without the field, give the same dry-run, the same
    files and the same doctor. (That a project without it is what the branch point gave is the cmp of the pull request.)"""
    with_profiles = {"profiles": {"default": "code", "offered": {"list": {}}}}
    anchor = "        bad = lib.project_error(prof)\n"
    loader = "        if 'profiles' in prof:\n            prof.setdefault('env', {})['PROFILES_LOADED'] = '1'\n"
    out = {}
    for label, kw in (("plain", {}), ("profiles", {"extra": with_profiles}),
                      ("mutated", {"extra": with_profiles, "mutate": ("forge/sync.py", anchor, loader + anchor)})):
        w = World(["app", "plain"], **kw)
        out[label] = {"sync --all (dry-run)": w.forge_cmd(["sync", "--all"]), "sync --apply app": w.forge_cmd(["sync", "--apply", "app"]),
                      "doctor": w.forge_cmd(["doctor"]), **w.files("projects")}

    def differs(label):
        a, b = out["plain"], out[label]
        return [(k if k.startswith("projects/") else "output of " + k) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    check("a: a project with `profiles` generates the same as one without", not differs("profiles"),
          "; ".join("%s differs" % k for k in differs("profiles")))
    check("a: the world generated a settings.local.json to compare", "projects/app/.claude/settings.local.json" in out["plain"],
          sorted(out["plain"]))
    # The control: a loader that adds a key when the field is there must turn the comparison red.
    check("a: the control (a loader that adds a key to the generated settings) is seen",
          "projects/app/.claude/settings.local.json" in differs("mutated"),
          "projects/app/.claude/settings.local.json did not differ: the comparison cannot fail (%s)" % differs("mutated"))


def lists_of(w, profile, project="multi"):
    code, out, err = w.forge_cmd(["list", "@" + profile, "--json"], cwd=w.pp(project))
    return code, (json.loads(out) if code == 0 else None), err


def main():
    w = World(["multi", "errs", "none", "frozen-p", "bad"])
    sandbox.git(w.pp("multi"), "commit", "-q", "--allow-empty", "-m", "c")
    tree = os.path.join(w.root, "linked")
    sandbox.git(w.pp("multi"), "worktree", "add", "-q", tree)
    world_before = w.files("")  # the reads below must not change any file of it

    # b: the expected lists.
    code, got, err = lists_of(w, "toy-b")
    mcporter = os.path.join(w.home, ".config", "mcporter", "mcporter.json").replace(w.root, "@S@")
    want = {"skills_keep": ["toy-a", "toy-b", "toy-c", "toy-common"], "plugins_keep": ["p-def@m", "toy-plugin@x"],
            "servers": ["toy-echo"], "permissions": {"allow": ["Read"]},
            "env": {"TOY_B": "1", "TOY_ENV": "1", "MCPORTER_CONFIG": mcporter}}
    check("b: toy-b resolves to the expected lists", code == 0 and all(
        json.loads(json.dumps(got.get(k)).replace(w.root, "@S@")) == v for k, v in want.items()), "got %r (%s), want %r" % (got, err, want))
    check("b: the card says who it is", got and (got["project"], got["profile"], got["description"], got["color"]) == ("multi", "toy-b", "toy B", "red"), got)
    # The profile does not inherit from the default: the default's own skill `toy-a` is there only because the set has it.
    check("b: the plugin the default has comes from the definition, not from the default",
          got and "p-def@m" in got["plugins_keep"], got)
    check("b: the difference with the default", got and got["differs_from_default"] == {
        "skills_keep": {"added": ["toy-b", "toy-c"], "removed": []}, "plugins_keep": {"added": ["toy-plugin@x"], "removed": []},
        "servers": {"added": ["toy-echo"], "removed": []}, "permissions": {"added": ["allow:Read"], "removed": []},
        "env": {"added": ["MCPORTER_CONFIG=" + mcporter, "TOY_B=1", "TOY_ENV=1"], "removed": ["TOY=1"]}}, got and got["differs_from_default"])

    # c: each way a resolution fails is exit 2 naming the profile and the cause.
    for profile, cause in (("err-set", "unknown skill set '@NOPE'"), ("err-skill", "unknown skill 'toy-missing'"),
                           ("err-kind", "the server kind 'search' has no server assigned"),
                           ("err-extra", "the kind 'search', which the definition does not list"),
                           ("err-nodef", "no definition: config/profile-defs/err-nodef.json does not exist")):
        code, out, err = w.forge_cmd(["list", "@" + profile], cwd=w.pp("errs"))
        check("c: %s is exit 2" % profile, code == 2, "exit %d, stderr %r" % (code, err))
        check("c: %s names the profile and the cause" % profile, ("profile '%s' of project 'errs'" % profile) in err and cause in err,
              "stderr %r, want it to name the profile and %r" % (err, cause))

    ex = DEFS["from-example"]
    check("c: examples/profile-def.json has every key of a definition and no other", {k for k in ex if not k.startswith("_")} == set(profiles.DEFINITION),
          sorted(ex))
    code, got, err = lists_of(w, "from-example", "errs")
    check("c: the example, copied as it is, is a definition (its _doc is documentation)", code == 0 and got["skills_keep"] == ["toy-common"]
          and got["servers"] == [], (code, got, err))

    # d: a malformed `profiles` leaves the project out of lib.projects() and names it.
    skipped = []
    code, out, err = w.forge_cmd(["doctor", "bad"])
    r = subprocess.run([sys.executable, "-c", "import json; from forge import lib; s = []; p = lib.projects(s); print(json.dumps([sorted(p), s]))"],
                       cwd=w.forge, env=sandbox.bare_env(w.home, w.root), capture_output=True, text=True, timeout=60)
    names, skipped = json.loads(r.stdout) if r.returncode == 0 else (None, None)
    check("d: the project with `profiles: 5` is left out", names is not None and "bad" not in names and "multi" in names, (names, r.stderr))
    check("d: and named, with the field", skipped == [["bad.claude.json", "profiles is not a JSON object"]], skipped)
    for label, body in (("a profiles that is not an object", 5), ("an offered that is a list", {"default": "code", "offered": []}),
                        ("a row that is a string", {"default": "code", "offered": {"x": "s"}}),
                        ("a skills that is not a list of strings", {"default": "code", "offered": {"x": {"skills": [1]}}}),
                        ("servers that are not strings", {"default": "code", "offered": {"x": {"servers": {"k": 1}}}}),
                        ("no default", {"offered": {}}), ("an unknown key", {"default": "code", "offered": {}, "extra": 1})):
        check("d: %s is refused" % label, lib.project_error({"profiles": body}), "accepted")

    # e: the name rules.
    ok = {"default": "code", "offered": {"list": {}, "shim": {}, "a1-b2": {}}}
    check("e: a profile named 'list' is valid (and 'shim')", lib.project_error({"profiles": ok}) is None,
          "profile named 'list' rejected: %s" % lib.project_error({"profiles": ok}))
    for name, reason in (("@x", "starts with @"), ("-x", "starts with -"), ("Big", "not kebab-case"), ("a_b", "not kebab-case"), ("x-", "not kebab-case")):
        why = lib.project_error({"profiles": {"default": "code", "offered": {name: {}}}})
        check("e: profile named '%s' is refused with the reason" % name, why is not None and repr(name) in why and reason in why,
              "profile named '%s' accepted or the reason is missing: %r" % (name, why))
    why = lib.project_error({"profiles": {"default": "code", "offered": {"code": {}}}})
    check("e: the default label repeated in offered is refused with the reason", why is not None and "'code'" in why and "repeats the default" in why, why)
    why = lib.project_error({"profiles": {"default": "@d", "offered": {}}})
    check("e: a default label is a name too", why is not None and "starts with @" in why, why)
    code, out, err = w.forge_cmd(["list", "@list"], cwd=w.pp("multi"))
    check("e: forge list @list shows its card", code == 0 and "profile list of project multi" in out and "named like the command" in out,
          "exit %d, %r, %r" % (code, out, err))
    for arg in ("@@x", "@-x", "@Big"):
        code, out, err = w.forge_cmd(["list", arg], cwd=w.pp("multi"))
        check("e: forge list %s is exit 2 with the reason" % arg, code == 2 and out == "" and "forge list:" in err and "@" in err, (code, out, err))

    # f: forge list @.
    code, out, err = w.forge_cmd(["list", "@"], cwd=w.pp("multi"))
    check("f: list @ exits 0", code == 0, "list @ exits %d with profiles: %r" % (code, err))
    check("f: the text has both profiles and the default", all(x in out for x in ("toy-b", "list", "code", "toy B", "red")), out)
    code, out, err = w.forge_cmd(["list", "@", "--json"], cwd=w.pp("multi"))
    rows = json.loads(out) if code == 0 else None
    check("f: --json has the default and both profiles", rows is not None and [r["name"] for r in rows] == ["code", "toy-b", "list"]
          and rows[1] == {"name": "toy-b", "default": False, "description": "toy B", "color": "red"}, (code, out, err))
    code, out, err = w.forge_cmd(["list", "@"], cwd=w.pp("none"))
    check("f: no profiles is exit 1", code == 1, "list @ exits %d with no profiles" % code)
    check("f: and says no profiles", "no profiles" in out + err, (out, err))
    code, out, err = w.forge_cmd(["list", "@", "--json"], cwd=w.pp("none"))
    check("f: --json with no profiles is the empty list", (code, json.loads(out) if out.strip() else None) == (1, []), (code, out, err))
    code, out, err = w.forge_cmd(["list", "@"], cwd=w.pp("frozen-p"))
    check("f: a frozen project is exit 1 and says so", code == 1 and "frozen" in out and "no profiles" in out, (code, out, err))
    code, out, err = w.forge_cmd(["list", "@"], cwd=w.home)
    check("f: a folder that is no project is exit 2", code == 2 and "not inside a project" in err, (code, out, err))
    code, out, err = w.forge_cmd(["list", "@", "--names"], cwd=tree)
    check("f: a linked worktree is its main checkout's project", code == 0 and out.split() == ["code", "toy-b", "list"], (code, out, err))
    for args in (["list"], ["list", "multi"]):
        code, out, err = w.forge_cmd(args, cwd=w.pp("multi"))
        check("f: forge %s is exit 2 with one line" % " ".join(args), code == 2 and out == "" and len(err.strip().splitlines()) == 1
              and "forge list:" in err and "@NAME" in err, (code, out, err))

    # g: forge list @NAME.
    code, out, err = w.forge_cmd(["list", "@toy-b"], cwd=w.pp("multi"))
    check("g: the card is printed", code == 0 and all(x in out for x in (
        "profile toy-b of project multi", "toy B", "red", "toy-a, toy-b, toy-c, toy-common", "p-def@m, toy-plugin@x", "toy-echo",
        "differs from the default", "skills_keep", "+toy-b +toy-c", "-TOY=1")), (code, out, err))
    code, js, err = lists_of(w, "toy-b")
    code, text, err = w.forge_cmd(["list", "@toy-b"], cwd=w.pp("multi"))
    strings = [x for k in ("skills_keep", "plugins_keep", "servers") for x in js[k]] + [js["description"], js["color"]] if js else []
    check("g: --json says what the text says", strings and all(s in text for s in strings), (strings, text))
    code, out, err = w.forge_cmd(["list", "@toy-c"], cwd=w.pp("multi"))
    check("g: an unknown profile is exit 2 naming the closest", code == 2 and "toy-b" in err, (code, out, err))
    code, out, err = w.forge_cmd(["list", "@toy-"], cwd=w.pp("multi"))
    check("g: @toy- proposes @toy-b", code == 2 and "did you mean '@toy-b'" in err, "no suggestion in: %s" % err.strip())
    code, out, err = w.forge_cmd(["list", "@code"], cwd=w.pp("multi"))
    check("g: the default's card is the project file as it is", code == 0 and "the default" in out and "toy-common, toy-a" in out
          and "differs" not in out, (code, out, err))
    check("g: suggest.closest finds a typo and not a stranger", suggest.closest("marketng", ["marketing", "code"]) == "marketing"
          and suggest.closest("zzzz", ["marketing", "code"]) is None, "closest")

    # h: --names.
    code, out, err = w.forge_cmd(["list", "@", "--names"], cwd=w.pp("multi"))
    check("h: --names is the names, one per line", code == 0 and out.split("\n") == ["code", "toy-b", "list", ""], (code, out, err))
    check("h: no @ in the --names output", "@" not in out, "@ in --names output: %r" % out)
    code, out, err = w.forge_cmd(["list", "@toy-b", "--names"], cwd=w.pp("multi"))
    check("h: --names with a profile is exit 2", code == 2, (code, out, err))

    check("no command above wrote a file in the world", w.files("") == world_before,
          "changed: %s" % sorted(k for k in set(w.files("")) | set(world_before) if w.files("").get(k) != world_before.get(k)))

    case_a()
    sandbox.cleanup()
    if failures:
        print("%d FAIL" % len(failures))
        return 1
    print("test_profiles: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
