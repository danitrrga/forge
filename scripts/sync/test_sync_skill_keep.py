#!/usr/bin/env python3
"""sync_skill_keep.py's COMMON_ENV layer and the per-project opt-out from it, in a toy world.

COMMON_OPT_OUT used to name COMMON_SKILLS / COMMON_PLUGINS entries only, and check_declared exited
1 on anything else. It now also names COMMON_ENV keys: apply_common neither adds an opted-out key
nor keeps one that is there, and check_declared accepts it.

A skill named gsd-* is trimmed like any other, whatever integrations.gsd says (see the last paragraph).

Two worlds. The mechanism runs on a copy of the script patched to carry a toy env key (TOY_KEY) and
to opt one project out of it, so it does not depend on what the real COMMON_ENV holds. The real
declaration runs the unpatched script over projects named like the real ones: the common layer
gives CLAUDE_CODE_SUBAGENT_MODEL=sonnet to a plain project, and not to the two opted-out
projects, nor to the excluded one (COMMON_EXCLUDE).

Seen failing on 09fb195: "mechanism: opt-out of an env key, exit and last line = (1,
'    COMMON_OPT_OUT[plain.claude.json] -> TOY_KEY is in neither COMMON_SKILLS nor COMMON_PLUGINS'),
want (0, '4 project(s) updated.')" and "real: plain project = None, want 'sonnet'". With check_declared
fixed and apply_common's skip mutated out: "mechanism: an opted-out key is stripped = True, want
False", "real: the quiet project is opted out = True, want False" and the same for the opt-out project.

Round 8, the third world: a stray notes.json and three bad projects (truncated, null,
a field of the wrong type) beside good ones. Seen failing on a00252c: "bad projects dry-run:
trunc.claude.json is named, unreadable, skipped = False, want True" (the same for null and typed,
and under --check and --apply), "bad projects dry-run: no traceback = ['Traceback (most recent call
last):'], want []" (json.load's JSONDecodeError, which never names the file), "bad projects
dry-run: the stray .json is not a project = ['  ~ notes.json   gsd baseline +[...]; skills
+[...]; perms +21; env MCPORTER_CONFIG; ...'], want []" and "bad projects: notes.json is left
byte-identical by --apply = '{\\n  \\"skills_keep\\": [...', want '{\\"skills_keep\\":
[\\"gsd-fast\\"]}\\n'" (the stray file was rewritten with the COMMON perms and env).

T3 of docs/portable-design.md: the tables are config/forge.json's skill_keep, so every
world is a toy forge.json (this checkout's with one table edited) instead of a patched copy of the
script, and six more worlds cover what only the file can say. Seen failing on 947b2e4, where the
tables were still code and the toy file was ignored: "no extras row: the project is only unioned = (False,
True, True), want (True, False, False)" (a project out of extras was still a full replace), "@SET: the
set's names are in = [False, False, False], want [True, True, True]", "@SET: an unknown set = (1,
False, False), want (1, True, False)", "~: expanded to the toy HOME = None, want '<HOME>/toy'",
"gsd off: plain.claude.json gets no other gsd-* name = ['gsd-ai-integration-phase', ...], want []"
(the same for zzz), and "stranger: --check = (1, "FileNotFoundError: ... home/.claude/skills"), want
(0, '0 project(s) would change.')". With the file read, "stranger" then failed on "~ toy.claude.json
perms +0": an empty table was a change forever. With TRACK_GSD = True patched in: both "gsd off"
cases and "stranger: --check, exit and its project line = (1, False, False), want (0, True, True)".

A skill named gsd-* is any other name: no baseline read off the disk, no table of its own, no strip with the integration
off. Seen failing on 61083ab (the layers were still there): "gsd on: extras project got from the gsd baseline =
['gsd-fast', 'gsd-toy', 'gsd-toy-0', ...], want []" (a project with an extras row), and, for the rest of that block,
"gsd off: the union project keeps its held gsd-fast, prunes gsd-gone, gains no baseline = [], want ['gsd-fast']" (a held
name stripped), "gsd on: ... = ['gsd-fast', 'gsd-toy', ...], want ['gsd-fast']" (a baseline gained), "gsd off: an extras
row naming a missing gsd-* skill is refused = (1, False), want (1, True)", "no gsd-* skill installed: --apply = (1,
[...]), want (0, [])" ("! no gsd-* skills found ... refusing to wipe keep-lists") and "gsd flipped on after an apply
with it off: --check = (1, '...'), want (0, '0 project(s) would change.')". Each world runs with the integration on and
off and must give the same result.
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "tests"))
import sandbox  # noqa: E402

SCRIPT = os.path.join("scripts", "sync", "sync_skill_keep.py")
KEY = "CLAUDE_CODE_SUBAGENT_MODEL"
failures = []

# Every world but one is built from tests/fixtures/config/forge.json plus the toy declaration below, never from
# this machine's config/forge.json: the mechanism does not depend on what a machine declares, and a
# checkout without that file has nothing to copy. Red before, on a copy_engine copy in a toy HOME (M1):
# "FileNotFoundError: .../config/forge.json" at world()'s open of it. The one world that pins THIS machine's
# declaration (`real:` below) runs on this machine's file where the checkout carries the tables it pins, and
# on the toy declaration of the same shape elsewhere, with the toy names in place of the real ones.
FIXTURE_JSON = os.path.join(sandbox.FORGE, "tests", "fixtures", "config", "forge.json")
REAL_JSON = os.path.join(sandbox.FORGE, "config", "forge.json")
TOY = {"plain": "plain.claude.json", "plain2": "plain2.claude.json", "optout": "optout.claude.json",
       "quiet": "quiet.claude.json", "excluded": "excluded.claude.json"}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def toy_declaration(sk):
    """The shape the real file declares, on toy names: KEY for every project but the opted-out and the excluded
    ones, and the plain one a full replace (an extras row)."""
    sk["common_env"][KEY] = "sonnet"
    sk["common_opt_out"].update({TOY["optout"]: [KEY], TOY["quiet"]: [KEY]})
    sk["common_exclude"].append(TOY["excluded"])
    sk["extras"][TOY["plain"]] = []


def pinned_from(doc, project_names):
    """The projects the `real:` world asserts on, by role, read from doc's own tables: plain, another plain, two
    opt-outs of KEY, the excluded one. None when the tables do not declare them (a stranger's checkout, a
    machine whose declaration changed). The names come from the data and never from this file, which is public."""
    sk = doc.get("skill_keep") or {}
    optout = sk.get("common_opt_out") or {}
    outs = sorted(n for n, keys in optout.items() if KEY in keys)
    excl = list(sk.get("common_exclude") or [])
    taken = set(outs[:2] + excl[:1])
    plain = [n for n in sorted(sk.get("extras") or {}) if n not in taken]
    plain2 = [n for n in project_names if n not in taken and n not in plain[:1]]
    if KEY not in (sk.get("common_env") or {}) or len(outs) < 2 or not excl or not plain or not plain2:
        return None
    return {"plain": plain[0], "plain2": plain2[0], "optout": outs[0], "quiet": outs[1], "excluded": excl[0]}


def real_pins():
    if not os.path.exists(REAL_JSON):
        return None
    pdir = os.path.join(sandbox.FORGE, "config", "projects")
    names = sorted(f for f in os.listdir(pdir) if f.endswith(".claude.json")) if os.path.isdir(pdir) else []
    return pinned_from(load(REAL_JSON), names)


PINNED = real_pins()  # {role: project file name} of this machine's declaration, or None
REAL = PINNED is not None
N = PINNED if REAL else TOY
PLAIN, PLAIN2, OPTOUT, QUIET, EXCLUDED = (N[k] for k in ("plain", "plain2", "optout", "quiet", "excluded"))
# The mechanism worlds are on toy names always; EXTRAS_FILE is the fixture's own extras row.
PLAIN_FILE, EXTRAS_FILE = TOY["plain"], "app.claude.json"
TOY_SKILLS = ["toy-common", "omarchy", "defuddle", "summarize", "watch", "gsd-fast", "gsd-toy"] + ["gsd-toy-%d" % i for i in range(12)]


def want(label, got, expected):
    if got != expected:
        failures.append("%s = %r, want %r" % (label, got, expected))


def world(tmp, name, projects, tables=None, gsd=True, forge_json=None, real=False):
    """(root, env): a toy forge holding the script, config/forge.json, the given projects ({file name:
    dict}), and a toy HOME with TOY_SKILLS installed, so check_declared finds every declared name
    installed. config/forge.json is the fixture's with toy_declaration() on it: `tables` (a function)
    edits its skill_keep in place and `gsd` sets the gsd integration; `forge_json` replaces the whole
    file. With `real` it is this checkout's own file, and the HOME holds every skill the checkout
    ships plus omarchy."""
    base = os.path.join(tmp, name)
    root, home = os.path.join(base, "forge"), os.path.join(base, "home")
    sandbox.mini_root(root, SCRIPT)
    if forge_json is None:
        forge_json = load(REAL_JSON if real else FIXTURE_JSON)
        forge_json["integrations"]["gsd"] = gsd
        if not real:
            toy_declaration(forge_json["skill_keep"])
        if tables:
            tables(forge_json["skill_keep"])
    os.makedirs(os.path.join(root, "config", "projects"))
    with open(os.path.join(root, "config", "forge.json"), "w", encoding="utf-8") as fh:
        json.dump(forge_json, fh)
    for fn, prof in projects.items():
        with open(os.path.join(root, "config", "projects", fn), "w", encoding="utf-8") as fh:
            json.dump(prof, fh)
    for skill in (os.listdir(os.path.join(sandbox.FORGE, "skills")) + ["omarchy"]) if real else TOY_SKILLS:
        os.makedirs(os.path.join(home, ".claude", "skills", skill))
    sandbox.installed_settings(home, root)
    return root, sandbox.bare_env(home, base)


def run(root, env, *flags):
    r = subprocess.run([sys.executable, SCRIPT] + list(flags), cwd=root, env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1]


def run_full(root, env, *flags):
    """(exit code, every output line): run() keeps only the last line."""
    r = subprocess.run([sys.executable, SCRIPT] + list(flags), cwd=root, env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).splitlines()


def env_of(root, fn):
    with open(os.path.join(root, "config", "projects", fn), encoding="utf-8") as fh:
        return json.load(fh).get("env", {})


def skills_of(root, fn):
    with open(os.path.join(root, "config", "projects", fn), encoding="utf-8") as fh:
        return json.load(fh)["skills_keep"]


def trimmed(**extra):
    return dict({"project": "toy", "skills_keep": ["gsd-fast"], "env": {}}, **extra)


# check_declared exits 1 for a COMMON_OPT_OUT entry whose project is missing, so a toy world has these.
OPT_OUT_PROJECTS = {fn: {"project": "toy", "skills_keep": ["gsd-fast"]} for fn in (TOY["optout"], TOY["quiet"])}


def main():
    tmp = sandbox.mkdtemp("skillkeep-test-")

    # The mechanism, on a config/forge.json carrying a toy key and an opt-out of it for the plain project.
    def toy_key(sk):
        sk["common_env"]["TOY_KEY"] = "toy"
        sk["common_opt_out"][PLAIN_FILE] = ["TOY_KEY"]
    root, env = world(tmp, "mech", {
        PLAIN_FILE: trimmed(env={"TOY_KEY": "stale"}),   # opted out, and carrying the key
        EXTRAS_FILE: trimmed(),                              # not opted out
        **OPT_OUT_PROJECTS,
    }, toy_key)
    code, last = run(root, env, "--apply")
    want("mechanism: opt-out of an env key, exit and last line", (code, last), (0, "4 project(s) updated."))
    want("mechanism: an opted-out key is stripped", "TOY_KEY" in env_of(root, PLAIN_FILE), False)
    want("mechanism: a project not opted out gets it", env_of(root, EXTRAS_FILE).get("TOY_KEY"), "toy")
    want("mechanism: the opted-out project still gets the other keys",
         "MCPORTER_CONFIG" in env_of(root, PLAIN_FILE), True)
    want("mechanism: the opted-out project is then in sync", run(root, env, "--check"),
         (0, "0 project(s) would change."))
    # An opt-out that names no COMMON name at all is still a typo and still refused.
    root, env = world(tmp, "typo", dict({PLAIN_FILE: trimmed()}, **OPT_OUT_PROJECTS),
                      lambda sk: sk["common_opt_out"].update({PLAIN_FILE: ["NO_SUCH_KEY"]}))
    r = subprocess.run([sys.executable, SCRIPT, "--check"], cwd=root, env=env, capture_output=True, text=True)
    want("mechanism: an opt-out naming nothing declared", (r.returncode, "NO_SUCH_KEY" in r.stdout + r.stderr), (1, True))

    # The real declaration: the unpatched script, projects named like the real ones.
    names = [PLAIN, QUIET, OPTOUT, EXCLUDED, PLAIN2]
    root, env = world(tmp, "real", {fn: trimmed(skills_keep=["omarchy"]) for fn in names}, real=REAL)
    if not REAL:
        print("NOT RUN: this machine's declaration (the tables the real: world pins are not in config/forge.json), "
              "so the real: world ran on the toy declaration of the same shape")
    want("real: --apply", run(root, env, "--apply")[0], 0)
    # The excluded project takes no common layer, and no other layer adds a skill: it is as it was.
    want("real: the excluded project keeps what it held", skills_of(root, EXCLUDED), ["omarchy"])
    want("real: a plain project keeps what it held", "omarchy" in skills_of(root, PLAIN2), True)
    want("real: plain project", env_of(root, PLAIN).get(KEY), "sonnet")
    want("real: another plain project", env_of(root, PLAIN2).get(KEY), "sonnet")
    want("real: the quiet project is opted out", KEY in env_of(root, QUIET), False)
    want("real: the opt-out project is opted out", KEY in env_of(root, OPTOUT), False)
    want("real: the excluded project takes no common layer", KEY in env_of(root, EXCLUDED), False)
    want("real: the force variable is never set",
         [fn for fn in names if KEY + "_FORCE" in env_of(root, fn)], [])
    want("real: --check after the apply", run(root, env, "--check"), (0, "0 project(s) would change."))

    # Round 8: only config/projects/*.claude.json is a project, and a project that cannot be read
    # is named and skipped, never a bare traceback. A stray notes.json sits beside the projects;
    # three bad projects (truncated, `null`, a field of the wrong type) sit beside two good ones.
    stray = '{"skills_keep": ["gsd-fast"]}\n'
    good = {fn: trimmed() for fn in (PLAIN_FILE, EXTRAS_FILE)}
    root, env = world(tmp, "bad", dict(good, **OPT_OUT_PROJECTS))
    pdir = os.path.join(root, "config", "projects")
    bad = {"trunc.claude.json": '{"project": "toy", "skills_keep": [', "null.claude.json": "null",
           "typed.claude.json": '{"project": "toy", "skills_keep": 5}', "notes.json": stray}
    for fn, text in bad.items():
        with open(os.path.join(pdir, fn), "w", encoding="utf-8") as fh:
            fh.write(text)
    for flags in ((), ("--check",), ("--apply",)):
        code, lines = run_full(root, env, *flags)
        label = "bad projects %s" % (" ".join(flags) or "dry-run")
        want(label + ": exit code", code, 1)
        for fn in ("trunc.claude.json", "null.claude.json", "typed.claude.json"):
            want("%s: %s is named, unreadable, skipped" % (label, fn),
                 [l for l in lines if l.startswith("! %s unreadable: " % fn) and l.endswith(" -- skipped")] != [], True)
        want(label + ": the good projects are still processed", [l for l in lines if PLAIN_FILE in l] != [], True)
        want(label + ": the stray .json is not a project", [l for l in lines if "notes.json" in l], [])
        want(label + ": no traceback", [l for l in lines if "Traceback" in l], [])
    for fn, text in bad.items():
        with open(os.path.join(pdir, fn), encoding="utf-8") as fh:
            want("bad projects: %s is left byte-identical by --apply" % fn, fh.read(), text)
    want("bad projects: --apply still wrote the good project", "toy-common" in skills_of(root, PLAIN_FILE), True)

    # T3 (docs/portable-design.md section 4): the tables are config/forge.json's skill_keep, not code.
    def line_of(lines, fn):
        return ([l for l in lines if fn in l] or [""])[0].strip()

    extras_prof = {EXTRAS_FILE: {"project": "toy", "skills_keep": ["gsd-fast", "defuddle"]}}
    # the project in extras: layer 1 is a full replace, so the hand-added defuddle is reported as removed.
    root, env = world(tmp, "extras-in", dict(extras_prof, **OPT_OUT_PROJECTS))
    code, lines = run_full(root, env, "--check")
    got = line_of(lines, EXTRAS_FILE)
    want("extras row: --check exit", code, 1)
    want("extras row: the project is a full replace, defuddle removed",
         (re.match(r"~ \S+\s+extras \+", got) is not None, "-['defuddle'" in got), (True, True))
    # The same project out of extras is only unioned: --check reports the COMMON skills it lacks and keeps defuddle.
    root, env = world(tmp, "extras-out", dict(extras_prof, **OPT_OUT_PROJECTS),
                      lambda sk: sk["extras"].pop(EXTRAS_FILE))
    code, lines = run_full(root, env, "--check")
    got = line_of(lines, EXTRAS_FILE)
    want("no extras row: --check exit", code, 1)
    want("no extras row: the project is only unioned", ("gsd" in got, "extras" in got, "defuddle" in got), (False, False, False))
    want("no extras row: --apply keeps defuddle", run(root, env, "--apply")[0], 0)
    want("no extras row: defuddle kept", "defuddle" in skills_of(root, EXTRAS_FILE), True)

    # @SET in an extras row expands to the set, in place; an unknown set is refused, naming it.
    def toy_set(sk):
        sk["sets"]["TOY_SET"] = ["defuddle", "summarize"]
        sk["extras"][PLAIN_FILE] = ["@TOY_SET", "watch"]
    root, env = world(tmp, "set", dict({PLAIN_FILE: trimmed()}, **OPT_OUT_PROJECTS), toy_set)
    want("@SET: --apply", run(root, env, "--apply")[0], 0)
    got = skills_of(root, PLAIN_FILE)
    want("@SET: the set's names are in", [n in got for n in ("defuddle", "summarize", "watch")], [True, True, True])
    want("@SET: no @ name is left", [n for n in got if n.startswith("@")], [])
    root, env = world(tmp, "set-typo", dict({PLAIN_FILE: trimmed()}, **OPT_OUT_PROJECTS),
                      lambda sk: sk["extras"].update({PLAIN_FILE: ["@NO_SUCH_SET"]}))
    r = subprocess.run([sys.executable, SCRIPT, "--check"], cwd=root, env=env, capture_output=True, text=True)
    want("@SET: an unknown set", (r.returncode, "NO_SUCH_SET" in r.stdout + r.stderr, "Traceback" in r.stderr), (1, True, False))

    # ~ in a common_env value is this HOME's, as os.path.join(HOME, ...) was.
    root, env = world(tmp, "tilde", dict({PLAIN_FILE: trimmed()}, **OPT_OUT_PROJECTS),
                      lambda sk: sk["common_env"].update({"TOY_PATH": "~/toy"}))
    want("~: --apply", run(root, env, "--apply")[0], 0)
    want("~: expanded to the toy HOME", env_of(root, PLAIN_FILE).get("TOY_PATH"), os.path.join(env["HOME"], "toy"))

    # A gsd-* name is any other name, with integrations.gsd on or off. The extras project (a full replace) holds no gsd-*
    # name afterwards and gets nothing from the disk's gsd-* skills; the union project (no extras row) keeps the gsd-*
    # name it holds, drops the one with no skill behind it (dangling, like any other) and gains none; the project
    # whose extras row names an installed gsd-* skill keeps it; the keep-all project is untouched.
    NAMED, STAR, ZZZ = "named.claude.json", "star.claude.json", "zzz.claude.json"
    held = dict({PLAIN_FILE: trimmed(skills_keep=["defuddle"]),
                 ZZZ: trimmed(skills_keep=["gsd-fast", "gsd-gone", "defuddle"]),
                 NAMED: trimmed(skills_keep=["gsd-toy-1", "defuddle"]),
                 STAR: trimmed(skills_keep=["*"])}, **OPT_OUT_PROJECTS)
    named_row = lambda sk: sk["extras"].update({NAMED: ["gsd-fast", "summarize"]})
    gsd_roots = {}
    for label, on in (("gsd on", True), ("gsd off", False)):
        root, env = world(tmp, "gsd-" + label.split()[1], held, named_row, gsd=on)
        gsd_roots[on] = (root, env)
        want("%s: --apply" % label, run(root, env, "--apply")[0], 0)
        want("%s: extras project got from the gsd baseline" % label,
             [n for n in skills_of(root, PLAIN_FILE) if n.startswith("gsd-")], [])
        want("%s: the union project keeps its held gsd-fast, prunes gsd-gone, gains no baseline" % label,
             [n for n in skills_of(root, ZZZ) if n.startswith("gsd-")], ["gsd-fast"])
        want("%s: the union project keeps defuddle" % label, "defuddle" in skills_of(root, ZZZ), True)
        want("%s: the extras row naming an installed gsd-* skill keeps it" % label,
             [n for n in skills_of(root, NAMED) if n.startswith("gsd-")], ["gsd-fast"])
        want("%s: the keep-all project is untouched" % label, skills_of(root, STAR), ["*"])
        want("%s: --check after the apply" % label, run(root, env, "--check"), (0, "0 project(s) would change."))
        # An extras row naming a gsd-* skill that is not installed is refused, as any missing name is.
        root, env = world(tmp, "gsd-gone-" + label.split()[1], held,
                          lambda sk: sk["extras"].update({NAMED: ["gsd-fast", "gsd-gone"]}), gsd=on)
        code, lines = run_full(root, env, "--check")
        want("%s: an extras row naming a missing gsd-* skill is refused" % label,
             (code, [l for l in lines if "EXTRAS[%s] -> gsd-gone" % NAMED in l] != []), (1, True))
    # Flipping the integration changes nothing: the apply with it off is in sync with it on.
    root, env = gsd_roots[False]
    fjson = os.path.join(root, "config", "forge.json")
    doc = load(fjson)
    doc["integrations"]["gsd"] = True
    with open(fjson, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    want("gsd flipped on after an apply with it off: --check", run(root, env, "--check"), (0, "0 project(s) would change."))
    # No gsd-* skill installed at all is not an abort (the baseline it used to refuse to wipe is gone).
    root, env = world(tmp, "no-gsd", {PLAIN_FILE: trimmed(skills_keep=["defuddle"]), **OPT_OUT_PROJECTS})
    skills_dir = os.path.join(env["HOME"], ".claude", "skills")
    for n in [d for d in os.listdir(skills_dir) if d.startswith("gsd-")]:
        shutil.rmtree(os.path.join(skills_dir, n))
    code, lines = run_full(root, env, "--apply")
    want("no gsd-* skill installed: --apply", (code, [l for l in lines if "no gsd-* skills found" in l]), (0, []))

    # A stranger's forge: examples/forge.json (every table empty, gsd off) and no ~/.claude/skills.
    with open(os.path.join(sandbox.FORGE, "examples", "forge.json"), encoding="utf-8") as fh:
        stranger = json.load(fh)
    root, env = world(tmp, "stranger", {"toy.claude.json": {"project": "toy"}}, forge_json=stranger)
    shutil.rmtree(os.path.join(env["HOME"], ".claude", "skills"))
    code, lines = run_full(root, env, "--check")
    got = line_of(lines, "toy.claude.json")
    want("stranger: --check, exit and its project line", (code, got.startswith("="), got.endswith("no change")),
         (0, True, True))

    for msg in failures:
        print("FAIL", msg)
    print("%d failure(s) over 12 worlds" % len(failures))
    sandbox.cleanup(failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
