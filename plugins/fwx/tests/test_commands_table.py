#!/usr/bin/env python3
"""The command grammar (tool, object, verb): every decided name routes to the handler its old name ran, every old name is refused
with one line naming the new one, `fwx --help` lists the new names and none of the old.

The decided table is written out below as data of this test, apart from lib/fwx/routes.py, so a row that goes missing or points at
another handler from there is found here. `scenario()` builds a toy copy of bin/fwx and lib/fwx with every command module replaced by a
stub that prints `STUB <module> <argv as JSON>`, runs each new name and each old name through the real bin/fwx, and returns what
differs from the table. The real handlers keep their own end-to-end tests (test_state_cli.py, test_plan_cli.py, ...), which call
them by the new names.

Seen red against master before lib/fwx/routes.py existed (bin/fwx routed by file name; 302 checks, 166 failed; first lines):
  FAIL: walk capture: routes to screenshot ['A', 'B']: got 'STUB walk ["capture", "A", "B"]', want 'STUB screenshot ["A", "B"]'
  FAIL: old name `screenshot` is refused with one line, naming `fwx walk capture`: got (0, 'STUB screenshot ["A"]\n', ''), want (2, '', "fwx screenshot: now 'fwx walk capture'\n")
  FAIL: session: routes to state ['resolve', 'A', 'B']: got ['fwx: unknown command: session'], want 'STUB state ["resolve", "A", "B"]'
  FAIL: lib/fwx/routes.py exists

Controls, each a copy of lib/fwx/routes.py changed in one place, seen red on the check named (the scenario is run on the copy):
  - the row `phase new` removed:
      FAIL: phase new: routes to state ['new-phase', 'A', 'B']: got ['fwx phase: unknown verb: new'], want 'STUB state ["new-phase", "A", "B"]'
  - `wave merge` pointed at `cleanup`:
      FAIL: wave merge: routes to wave ['integrate', 'A', 'B']: got 'STUB wave ["cleanup", "A", "B"]', want 'STUB wave ["integrate", "A", "B"]'
  - `wave prepare` no longer an old name:
      FAIL: old name `wave prepare` is refused with one line, naming `fwx wave new`: got (0, 'STUB wave ["summary", "prepare", "A"]\n', ''), want (2, '', "fwx wave prepare: now 'fwx wave new'\n")
  - the flag row `linear list --waiting` gone:
      FAIL: linear list --waiting: routes to linear ['waiting', 'A', 'B']: got 'STUB linear ["list", "--waiting", "A", "B"]', want 'STUB linear ["waiting", "A", "B"]'
  - the default of `wave` gone:
      FAIL: default of `wave --run R`: routes to wave ['summary', '--run', 'R']: got ['fwx wave: unknown verb: --run'], want 'STUB wave ["summary", "--run", "R"]'
"""
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

s = helpers.Suite()

# (new name, old name or None, module, handler argv before the user's own) -- gramatica-decidida.md, "fwx: hoy -> decidido"
DECIDED = [
    ("budget", None, "budget", []), ("model", None, "model", []),
    ("statusline", None, "statusline", []), ("rounds", None, "rounds", []), ("stage", None, "stage", []),
    ("decide", None, "decide", []), ("verify", None, "verify", []),
    ("walk capture", "screenshot", "screenshot", []),
    ("session", "state resolve", "state", ["resolve"]), ("session attach", "state use", "state", ["use"]),
    ("phase list", "state list", "state", ["list"]), ("phase new", "state new-phase", "state", ["new-phase"]),
    ("subphase new", "state new-subphase", "state", ["new-subphase"]), ("milestone new", "state new-milestone", "state", ["new-milestone"]),
    ("phase remove", "state cancel", "state", ["cancel"]), ("decision new", "state decision", "state", ["decision"]),
    ("decision list", "state decisions", "state", ["decisions"]),
    ("state lint", "state check state", "state", ["check-state"]), ("report lint", "state check report", "state", ["check-report"]),
    ("plan lint", "plan check", "plan", ["check"]), ("plan brief", None, "plan", ["brief"]), ("plan status", None, "plan", ["status"]),
    ("context new", "context-base build", "context_base", ["build"]), ("context seal", "context-base seal", "context_base", ["seal"]),
    ("context lint", "context-base check", "context_base", ["check"]), ("context audit", "context-base audit", "context_base", ["audit"]),
    ("discuss", "discuss start", "discuss", ["start"]),
    ("playbook list", "playbooks tree", "playbooks", ["tree"]), ("playbook lint", "playbooks check", "playbooks", ["check"]),
    ("linear list", None, "linear", ["list"]), ("linear list --waiting", "linear waiting", "linear", ["waiting"]),
    ("linear new", "linear create", "linear", ["create"]), ("linear comment", None, "linear", ["comment"]),
    ("linear label", None, "linear", ["label"]),
    ("project state", None, "project_state", []),
    ("wave new", "wave prepare", "wave", ["prepare"]), ("base", "wave check-base", "wave", ["check-base"]),
    ("scratch new", "wave scratch", "wave", ["scratch"]), ("wave merge", "wave integrate", "wave", ["integrate"]),
    ("wave fix", "wave fix-round", "wave", ["fix-round"]), ("wave revert", None, "wave", ["revert"]),
    ("wave remove", "wave cleanup", "wave", ["cleanup"]), ("wave", "wave summary", "wave", ["summary"]),
    ("walk start", "walk up", "walk", ["up"]), ("walk stop", "walk down", "walk", ["down"]),
    ("walk stop --orphans", "walk sweep", "walk", ["sweep"]), ("walk ab", None, "walk", ["ab"]), ("walk pw", None, "walk", ["pw"]),
    ("control new", "walk arm-control", "walk", ["arm-control"]), ("control judge", None, "walk", ["control-judge"]), ("walk converge", "walk findings", "walk", ["findings"]),
    ("review new", "walk review-page", "walk", ["review-page"]), ("review read", "walk review-answers", "walk", ["review-answers"]),
    ("walk selftest", None, "walk", ["selftest"]),
    ("migrate-gsd", None, "migrate_gsd", []),
    # not in the table, kept under the name they have (their units are others', or the table does not name them)
    ("walk check-screens", None, "walk", ["check-screens"]),
    ("wave setup", None, "wave", ["setup"]),
]
# what `fwx OBJECT` with no verb runs: (words, handler module, handler argv)
DEFAULTS = [
    (["wave", "--run", "R"], "wave", ["summary", "--run", "R"]),
    (["session", "--json"], "state", ["resolve", "--json"]),
    (["decision", "--all"], "state", ["decisions", "--all"]),
    (["context", "DIR"], "context_base", ["check", "DIR"]),
    (["linear", "--label", "L"], "linear", ["list", "--label", "L"]),
    (["linear", "--project", "P", "list", "--waiting"], "linear", ["waiting", "--project", "P"]),
    (["linear", "--project", "P", "new"], "linear", ["create", "--project", "P"]),
    (["linear", "--project=P", "list", "--waiting"], "linear", ["waiting", "--project=P"]),
    (["linear", "--waiting"], "linear", ["waiting"]),
    (["linear", "--project", "P", "--waiting", "--json"], "linear", ["waiting", "--project", "P", "--json"]),
    (["discuss", "--json"], "discuss", ["start", "--json"]),
]
OBJECT_OLD = {"context-base": "context", "playbooks": "playbook"}
# the module whose handlers print their own argparse help for `--help`: the router leaves its rows to them
OWN_HELP = "state"


def build(mutate=None):
    """A toy copy of bin/fwx and lib/fwx whose command modules are stubs; `mutate(routes_text)` changes the copy of routes.py."""
    work = helpers.mkdtemp("fwx-table-")
    os.makedirs(os.path.join(work, "bin"))
    shutil.copy(os.path.join(helpers.ROOT, "bin", "fwx"), os.path.join(work, "bin", "fwx"))
    shutil.copytree(os.path.join(helpers.ROOT, "lib", "fwx"), os.path.join(work, "lib", "fwx"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    commands = os.path.join(work, "lib", "fwx", "commands")
    for f in os.listdir(commands):
        if f.endswith(".py") and f != "__init__.py":
            module = f[:-3]
            helpers.write(commands, f, '"""Stub of %s."""\nimport json\n\n\ndef main(argv):\n    print("STUB %s " + json.dumps(argv))\n'
                          '    return 0\n' % (module, module))
    if mutate:
        path = os.path.join(work, "lib", "fwx", "routes.py")
        with open(path) as fh:
            text = fh.read()
        new = mutate(text)
        assert new != text, "the control changed nothing"
        with open(path, "w") as fh:
            fh.write(new)
    return work


def run(work, *args):
    return subprocess.run([sys.executable, os.path.join(work, "bin", "fwx")] + list(args), cwd=work, env=helpers.clean_env(),
                          capture_output=True, text=True)


def stub(module, argv):
    return "STUB %s %s" % (module, json.dumps(argv))


def scenario(work):
    """[(check label, got, want)] for every check; the caller counts the ones where got != want."""
    out = []

    def check(label, got, want):
        out.append((label, got, want))

    for new, old, module, prefix in DECIDED:
        flag = [w for w in new.split() if w.startswith("--")]
        words = [w for w in new.split() if not w.startswith("--")]
        # the words of the name, then the flag where the name has one, then arguments of the user's own
        r = run(work, *(words + flag + ["A", "B"]))
        want = prefix + ["A", "B"]
        check("%s: routes to %s %s" % (new, module, want), r.stdout.strip() or r.stderr.strip().splitlines()[:1],
              stub(module, want))
        check("%s: exit code" % new, r.returncode, 0)
        if old:
            r = run(work, *(old.split() + ["A"]))
            check("old name `%s` is refused with one line, naming `fwx %s`" % (old, new), (r.returncode, r.stdout, r.stderr),
                  (2, "", "fwx %s: now 'fwx %s'\n" % (old, new)))
    for words, module, want in DEFAULTS:
        r = run(work, *words)
        check("default of `%s`: routes to %s %s" % (" ".join(words), module, want), r.stdout.strip() or r.stderr.strip().splitlines()[:1],
              stub(module, want))
    for old, new in OBJECT_OLD.items():
        r = run(work, old)
        check("old object `%s` is refused, naming `fwx %s`" % (old, new), (r.returncode, r.stdout, r.stderr),
              (2, "", "fwx %s: now 'fwx %s'\n" % (old, new)))
    r = run(work, "state", "check")
    check("old `state check` names both new names", (r.returncode, r.stderr), (2, "fwx state check: now 'fwx state lint' or 'fwx report lint'\n"))
    # `fwx test` left the table: the suite is run by forge as a group (`forge test fwx`), and the refusal names that, outside fwx. Red on master
    # (the command was a row and ran the suite of the working folder):
    #   FAIL: old `fwx test` is refused with one line naming `forge test fwx`: got (0, 'STUB test []\n', ''), want (2, '', "fwx test: now 'forge test fwx'\n")
    #   FAIL: fwx test: no command of the table runs it: got 'STUB test []', want ''
    for args in (("test",), ("test", "--jobs", "2"), ("test", "--expect-not-run", "tests/test_x.py")):
        r = run(work, *args)
        check("old `fwx %s` is refused with one line naming `forge test fwx`" % " ".join(args), (r.returncode, r.stdout, r.stderr),
              (2, "", "fwx test: now 'forge test fwx'\n"))
    r = run(work, "--help")
    check("--help does not list `fwx test`", bool(re.search(r"^  fwx test\b", r.stdout, re.M)), False)
    # `--help` and `-h` after a verb ask for help and run nothing: the router answers with the object's verb table on stdout, exit 0,
    # for every row but the rows of OWN_HELP (their real handler is checked below). A stub that prints STUB is a handler that ran.
    # Seen red on the router before this (`--help` went to the handler after a verb), and the same for `-h`:
    #   FAIL: `--help` after a verb prints help and runs nothing, on 55 rows: 43 failed, e.g. ['budget --help (exit 0, reached the handler)',
    #         'model --help (exit 0, reached the handler)']
    #   FAIL: real `fwx walk selftest --help`: exit 0, usage on stdout, nothing on stderr: got (2, False, '--help is not an option of this
    #         command\nusage: fwx walk selftest [--dir D] [--repo P] [--image-id ID] [--json]\n'), want (0, True, '')
    # Control: routes.py with the interception made inert (`and row[2] != OWN_HELP` -> `and False`) is seen red on the same check.
    for flagword in ("--help", "-h"):
        bad = []
        for new, old, module, prefix in DECIDED:
            for given in dict.fromkeys((tuple(w for w in new.split() if not w.startswith("--")), tuple(new.split()))):  # a flag row also with its flag
                r = run(work, *(list(given) + [flagword]))
                reached = "STUB" in r.stdout
                if r.returncode != 0 or not r.stdout.strip() or (reached and module != OWN_HELP):
                    bad.append("%s %s (exit %d%s)" % (" ".join(given), flagword, r.returncode, ", reached the handler" if reached else ""))
                    break
        check("`%s` after a verb prints help and runs nothing, on %d rows: %d failed, e.g. %s" % (flagword, len(DECIDED), len(bad), bad[:2]),
              bad, [])
    # unknown names and verbs
    for args, text in ((("nosuch",), "unknown command: nosuch"), (("phase", "nwe"), "unknown verb: nwe"), (("phase",), "needs a verb"),
                       (("../commands/budget",), "unknown command"), (("Budget",), "unknown command"),
                       # the cap of agents is a number of the configuration (D90): no command answers how many can start now, and the old
                       # names are not refused with a "now ...": there is no natural target. Red on master (both were rows of the table):
                       #   FAIL: fwx capacity: exit 2 and 'unknown command: capacity': got (0, False, ...)
                       #   FAIL: fwx walk capacity: exit 2 and 'unknown verb: capacity': got (0, False, ...)
                       (("capacity",), "unknown command: capacity"), (("walk", "capacity"), "unknown verb: capacity")):
        r = run(work, *args)
        check("fwx %s: exit 2 and %r" % (" ".join(args), text), (r.returncode, text in r.stderr, r.stdout), (2, True, ""))
    # the listing
    r = run(work, "--help")
    listed = {re.split(r"\s{2,}", line.strip()[4:], maxsplit=1)[0] for line in r.stdout.splitlines() if line.startswith("  fwx ")}
    check("--help: exit code", r.returncode, 0)
    for new, old, module, prefix in DECIDED:
        check("--help lists `fwx %s`" % new, new in listed, True)
        if old and old != new:
            check("--help does not list `fwx %s`" % old, old in listed, False)
            check("--help: no line says `fwx %s`" % old, bool(re.search(r"\bfwx " + re.escape(old) + r"(?![\w-])", r.stdout)), False)
    check("--help names no capacity command", "capacity" in r.stdout, False)
    r = run(work, "walk", "--help")
    check("`fwx walk --help` names no capacity verb", "capacity" in r.stdout, False)
    r = run(work, "wave", "--help")
    verbs = {re.split(r"\s{2,}", line.strip()[4:], maxsplit=1)[0] for line in r.stdout.splitlines() if line.startswith("  fwx ")}
    check("`fwx wave --help` lists the verbs of wave and no other object",
          verbs, {"wave", "wave new", "wave merge", "wave fix", "wave revert", "wave remove", "wave setup"})
    return out


def failures(out):
    return [(label, got, want) for label, got, want in out if got != want]


work = build()
out = scenario(work)
for label, got, want in out:
    s.eq(label, got, want)
s.ok("the scenario looked at every decided row and more (%d checks)" % len(out), len(out) > 4 * len(DECIDED), len(out))

# every module of lib/fwx/commands/ is the module of a row, and every row's module is a file: a new command cannot be forgotten
ROUTES = os.path.join(helpers.ROOT, "lib", "fwx", "routes.py")
if not os.path.exists(ROUTES):
    s.ok("lib/fwx/routes.py exists", False, ROUTES)
else:
    spec = importlib.util.spec_from_file_location("routes", ROUTES)
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    files = {f[:-3] for f in os.listdir(os.path.join(helpers.ROOT, "lib", "fwx", "commands")) if f.endswith(".py") and f != "__init__.py"}
    s.eq("every command file has a row", sorted(files - {r[2] for r in routes.ROWS}), [])
    s.eq("every row names a command file", sorted({r[2] for r in routes.ROWS} - files), [])
    s.eq("the table has the rows of the decided table, no more, no fewer",
         sorted((r[0], r[1], r[2], r[3]) for r in routes.ROWS), sorted((n, o, m, a) for n, o, m, a in DECIDED))

# the controls: the same scenario on a copy of routes.py with one line broken must go red on the named check
CONTROLS = (
    ("a row removed", lambda t: re.sub(r'    \("phase new".*\n', "", t), "phase new: routes to"),
    ("a row pointed at another handler", lambda t: t.replace('("wave merge", "wave integrate", "wave", ["integrate"]',
                                                             '("wave merge", "wave integrate", "wave", ["cleanup"]'),
     "wave merge: routes to"),
    ("an old name forgotten", lambda t: t.replace('("wave new", "wave prepare"', '("wave new", None'), "old name `wave prepare` is refused"),
    ("the refusal of `fwx test` forgotten", lambda t: t.replace('("test",): "\'forge test fwx\'"', '("testx",): "\'forge test fwx\'"'),
     "old `fwx test` is refused"),
    ("`--help` after a verb left to the handler", lambda t: t.replace("and row[2] != OWN_HELP", "and False"),
     "`--help` after a verb prints help"),
    ("a flag row gone", lambda t: re.sub(r'    \("linear list --waiting".*\n', "", t), "linear list --waiting: routes to"),
    ("the default of an object gone", lambda t: t.replace('("wave", "wave summary", "wave", ["summary"]', '("wave summary", None, "wave", ["summary"]'),
     "default of `wave --run R`"),
)
for name, mutate, label in CONTROLS if os.path.exists(ROUTES) else ():
    bad = failures(scenario(build(mutate)))
    s.ok("control (%s) is seen red on `%s...` (%d failed)" % (name, label, len(bad)), any(b[0].startswith(label) for b in bad), bad[:2])

# ---- the texts agents read name no command that is gone ------------------------------------------------------------------
# A removed command (`fwx capacity`, D90) lived on in a playbook line nothing read, and the workflow no longer did what it said. The base
# context's own check (`context_base._unknown_commands`, which knows the table and its old names) is run over every playbook, agent,
# skill, reference and the README: each `fwx <object> [word]` they name must be a command. Seen red on the head of PR 140
# (playbooks/execute.md still said the workflow runs `fwx capacity --role executor --want N --wait 540`):
#   FAIL: playbooks/execute.md names no command that is gone: ['unknown command: fwx capacity']
sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import context_base as _cb  # noqa: E402

texts = sorted(glob.glob(os.path.join(helpers.ROOT, "playbooks", "*.md")) + glob.glob(os.path.join(helpers.ROOT, "agents", "*.md"))
               + glob.glob(os.path.join(helpers.ROOT, "skills", "*", "SKILL.md")) + glob.glob(os.path.join(helpers.ROOT, "skills", "*", "references", "*.md"))
               + [os.path.join(helpers.ROOT, "README.md")])
s.ok("the scan looks at the playbooks, the agents, the skills and the README (%d files)" % len(texts),
     any("playbooks" + os.sep in p for p in texts) and any("agents" + os.sep in p for p in texts) and any(p.endswith("SKILL.md") for p in texts) and len(texts) > 20, len(texts))
for p in texts:
    with open(p, encoding="utf-8") as f:
        s.eq("%s names no command that is gone" % os.path.relpath(p, helpers.ROOT), _cb._unknown_commands(f.read()), [])
# control: the scan does see a removed command
s.eq("control: a text that names `fwx capacity` is caught", _cb._unknown_commands("it runs `fwx capacity --role executor`"), ["unknown command: fwx capacity"])

# ---- `--help` after a verb, on the real handlers --------------------------------------------------------------------------
# The reported case: `fwx walk selftest --help` printed "--help is not an option of this command" on stderr and exited 2. Run as the
# real command in an empty folder with an empty environment, so it needs no project, no key and no configuration.
empty = helpers.mkdtemp("fwx-help-")
REAL_FWX = os.path.join(helpers.ROOT, "bin", "fwx")


def real_help(*args):
    return subprocess.run([sys.executable, REAL_FWX] + list(args), cwd=empty, env={}, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=60)


r = real_help("walk", "selftest", "--help")
s.eq("real `fwx walk selftest --help`: exit 0, usage on stdout, nothing on stderr",
     (r.returncode, "usage: fwx walk" in r.stdout and "fwx walk selftest" in r.stdout, r.stderr), (0, True, ""))
# the rows left to their own handler print real help too
own = [n for n, o, m, a in DECIDED if m == OWN_HELP]
bad = []
for n in own:
    r = real_help(*([w for w in n.split() if not w.startswith("--")] + ["--help"]))
    if r.returncode != 0 or "usage:" not in r.stdout:
        bad.append("%s (exit %d)" % (n, r.returncode))
s.eq("the %d rows of module `%s` print their own help on `--help`" % (len(own), OWN_HELP), bad, [])
s.ok("that loop looked at rows", len(own) > 5, len(own))

# ---- the skills the texts offer exist ------------------------------------------------------------------------------------
# The discuss offered `/fwx:improve` for a request, and no skill of that name exists (it is a planned part): nothing read it. Every
# `/fwx:<name>` in a skill, agent, playbook or workflow must be a folder of skills/ or a file of workflows/. Seen red on master:
#   FAIL: skills/discuss/SKILL.md names no skill or workflow: write it or remove the line: ['skills/discuss/SKILL.md:18: /fwx:improve']
SLASH = re.compile(r"(?<![\w/.:-])/fwx:([a-z][a-z0-9-]*)")


def _unknown_slash(text, known):
    """['LINE: /fwx:name', ...] for each `/fwx:<name>` of text that is not in known, and the number of names looked at."""
    bad, seen = [], 0
    for n, line in enumerate(text.splitlines(), 1):
        for m in SLASH.finditer(line):
            seen += 1
            if m.group(1) not in known:
                bad.append("%d: /fwx:%s" % (n, m.group(1)))
    return bad, seen


known = ({d for d in os.listdir(os.path.join(helpers.ROOT, "skills")) if os.path.isfile(os.path.join(helpers.ROOT, "skills", d, "SKILL.md"))}
         | {f[:-3] for f in os.listdir(os.path.join(helpers.ROOT, "workflows")) if f.endswith(".js")})
slash_texts = texts + sorted(glob.glob(os.path.join(helpers.ROOT, "workflows", "*.js")))
looked = 0
for p in slash_texts:
    with open(p, encoding="utf-8") as f:
        bad, seen = _unknown_slash(f.read(), known)
    looked += seen
    rel = os.path.relpath(p, helpers.ROOT)
    s.eq("%s names no skill or workflow: write it or remove the line" % rel, ["%s:%s" % (rel, b) for b in bad], [])
s.ok("the `/fwx:` scan looked at %d names in %d files (zero is a failure)" % (looked, len(slash_texts)), looked > 0 and "execute" in known, looked)
# control: a text that names `/fwx:nope` is caught, and a real name is not
s.eq("control: a text that names `/fwx:nope` is caught", _unknown_slash("a\nthen give `/fwx:nope`", known), (["2: /fwx:nope"], 1))
s.eq("control: a text that names a skill and a workflow is not", _unknown_slash("`/fwx:discuss` and /fwx:execute", known), ([], 2))

s.done()
