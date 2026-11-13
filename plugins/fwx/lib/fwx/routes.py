"""The names of fwx's commands: tool, object, verb (`fwx phase new`), and the handler each one runs.

The one table. `bin/fwx` reads it to route, to list and to refuse an old name; nothing else decides what a command is called.
It is data and imports nothing, so a command that is asked for loads only its own module.

A row is (new name, old name, module, handler arguments, help):
  - new name: the words after `fwx`. An object alone (`wave`, `linear`, `context`, `session`, `decision`) is the object's default
    verb. A word starting with `--` makes the row apply only when that flag is among the arguments (`linear list --waiting`);
    the flag is not passed on.
  - old name: what the command was called before the grammar (None: it did not change). It is refused: exit 2 and one line,
    `fwx <old>: now 'fwx <new>'`. That line is the only compatibility there is.
  - module, handler arguments: the file of lib/fwx/commands/ and the words put before the user's arguments, so the handler keeps
    the argument parsing it always had.
"""

ROWS = [
    # one word
    ("budget", None, "budget", [], "the session's context and weekly quota budget: [--json] [--transcript PATH]"),
    ("capacity", None, "capacity", [], "how many agents of a role can start now: --role R --want N [--per-agent-mb M] [--wait S] [--unattended] [--json]"),
    ("model", None, "model", [], "the model for a role and size: <role> <size>"),
    ("statusline", None, "statusline", [], "the status-bar line, saving the session's budget"),
    ("rounds", None, "rounds", [], "count a job's implement-verify rounds against the cap: <dir> [--use MOTIVE | --reset MOTIVE]"),
    ("stage", None, "stage", [], "change the stage of a phase or a job, only where data/stages.json allows it: <dir> <stage> [--why TEXT]"),
    ("decide", None, "decide", [], "the merge decision for the facts of a PR: --facts FILE"),
    ("verify", None, "verify", [], "run the project's checks on a clean tree at the exact commit and record the evidence: [--json] [--pr N] [--dir PATH]"),
    ("test", None, "test", [], "run every tests/test_*.py of the working folder and summarise"),
    ("discuss", "discuss start", "discuss", ["start"], "what the discuss opens with, as one JSON: [--json] [--phase PHASE_DIR]"),
    ("migrate-gsd", None, "migrate_gsd", [], "convert a project's GSD `.planning/` to `.fwx/`: plan|refs|apply|leftovers [...]"),
    # the session, the phases, the milestones, the decisions and the files of the state
    ("session", "state resolve", "state", ["resolve"], "which phase the session is in, binding it when exactly one is open: [--json] [--session ID]"),
    ("session attach", "state use", "state", ["use"], "bind the session to a phase folder, a subproject or the root"),
    ("phase list", "state list", "state", ["list"], "the milestones and phases of a scope, with each phase's stage"),
    ("phase new", "state new-phase", "state", ["new-phase"], "make the next phase folder and bind the session to it"),
    ("phase remove", "state cancel", "state", ["cancel"], "delete a phase whose discuss was cancelled, and nothing else"),
    ("subphase new", "state new-subphase", "state", ["new-subphase"], "make the next subphase folder of a phase"),
    ("milestone new", "state new-milestone", "state", ["new-milestone"], "make the next milestone (or vN) of a scope"),
    ("decision new", "state decision", "state", ["decision"], "add a row to the phase's decisions.tsv, or with --adr to the scope's adr.tsv"),
    ("decision list", "state decisions", "state", ["decisions"], "the rows of a decisions.tsv in force (or --all), or those a topic touches (--grep)"),
    ("state lint", "state check state", "state", ["check-state"], "lint a state.md: an error for a rule, a WARN line for a length"),
    ("report lint", "state check report", "state", ["check-report"], "lint a phase report: an error for a rule, a WARN line for a length"),
    # the plan, the base context, the playbooks
    ("plan lint", "plan check", "plan", ["check"], "lint the plan files of a phase: <dir> [--json]"),
    ("plan brief", None, "plan", ["brief"], "the brief the agent of a step runs: <dir> <premortem|plan|postmortem> [--unattended] [--diff BASE..BRANCH] [--head]"),
    ("plan status", None, "plan", ["status"], "the status line of a step once it has run: <dir> <premortem|plan|postmortem> [--unattended]"),
    ("context new", "context-base build", "context_base", ["build"], "write the base-context file of a phase, subphase or job folder: <dir> [--map F]"),
    ("context seal", "context-base seal", "context_base", ["seal"], "put the mark on a base file written by hand: <file> [--source F]"),
    ("context lint", "context-base check", "context_base", ["check"], "lint the base context of a phase: <dir> | --file F | --project P"),
    ("context audit", "context-base audit", "context_base", ["audit"], "which agent of a session did not get the base its type should get"),
    ("playbook list", "playbooks tree", "playbooks", ["tree"], "the workflow tree, one node per line with its exits: [--tree PATH] [--scope NAME]"),
    ("playbook lint", "playbooks check", "playbooks", ["check"], "lint the playbooks against the workflow tree: [--tree PATH] [--only NAME]"),
    # Linear
    ("linear list", None, "linear", ["list"], "the issues of the project with a label: [--project NAME] --label L [--json]"),
    ("linear list --waiting", "linear waiting", "linear", ["waiting"], "the issues waiting for the owner, and how many: [--json]"),
    ("linear new", "linear create", "linear", ["create"], "create issues from JSON on stdin: --template T"),
    ("linear comment", None, "linear", ["comment"], "comment on an issue, the body on stdin: ISSUE --kind K"),
    ("linear label", None, "linear", ["label"], "add and remove neutral labels: ISSUE +L -L ..."),
    # the waves of a part and the checkout an agent writes in
    ("wave", "wave summary", "wave", ["summary"], "did a run's gate pass (the default of `wave`): --run R [--part-dir D]"),
    ("wave new", "wave prepare", "wave", ["prepare"], "prepare a part for `execute`: --part-dir D --plane session|factory --branch W [...]"),
    ("wave merge", "wave integrate", "wave", ["integrate"], "join the branches of a wave and run the gate: --part-dir D --run R (--branches B... | --final)"),
    ("wave fix", "wave fix-round", "wave", ["fix-round"], "decide whether a failure may be fixed, spending a round: --part-dir D --why TEXT [--run R]"),
    ("wave revert", None, "wave", ["revert"], "undo the commits of findings: --part-dir D --run R --findings IDS"),
    ("wave remove", "wave cleanup", "wave", ["cleanup"], "remove what a run's waves left: --run R"),
    ("wave setup", None, "wave", ["setup"], "run the project's worktree setup in the current linked worktree: [--force]"),
    ("base", "wave check-base", "wave", ["check-base"], "step 0 of an agent that writes: exit 42 unless the worktree starts at the commit: <sha> [--worktree P]"),
    ("scratch new", "wave scratch", "wave", ["scratch"], "the folder an agent writes its report and its TMPDIR in: <run> <unit>"),
    # the UI walk
    ("walk start", "walk up", "walk", ["up"], "start the app and a run"),
    ("walk stop", "walk down", "walk", ["down"], "close a run: its browsers, its app, its files"),
    ("walk stop --orphans", "walk sweep", "walk", ["sweep"], "stop every open run whose owner process is gone"),
    ("walk ab", None, "walk", ["ab"], "agent-browser, guarded to the run's own app"),
    ("walk pw", None, "walk", ["pw"], "Playwright, guarded to the run's own app"),
    ("walk check-screens", None, "walk", ["check-screens"], "check the screens a part changed against the walk's own list"),
    ("walk capacity", None, "walk", ["capacity"], "how many walkers can start now"),
    ("walk converge", "walk findings", "walk", ["findings"], "the walkers' verdicts into fix.json and contradicted.json"),
    ("walk selftest", None, "walk", ["selftest"], "the walk's own check on a toy app"),
    ("walk capture", "screenshot", "screenshot", [], "one capture per walked screen of a run, with no model: --run R [--screens JSON] [--out DIR]"),
    ("control new", "walk arm-control", "walk", ["arm-control"], "plant the control the walkers must find"),
    ("review new", "walk review-page", "walk", ["review-page"], "the review page the owner answers"),
    ("review read", "walk review-answers", "walk", ["review-answers"], "the owner's answers from the review page"),
]

# An old name of a whole object that no longer exists (any verb of it): the object that replaced it.
OLD_OBJECTS = {"context-base": "context", "playbooks": "playbook"}
# An old name that two new ones replaced.
OLD_EXTRA = {("state", "check"): "'fwx state lint' or 'fwx report lint'"}
# Options that come before the verb and take a value: `fwx linear --project NAME list`.
LEADING = {"linear": ("--project",)}
# The verb that `fwx OBJECT` alone runs, for an object whose default is one of its verbs (an object with a row of its own, such as
# `wave` or `session`, is that row's default).
DEFAULTS = {"decision": "list", "context": "lint", "linear": "list"}


def words(name):
    return tuple(name.split())


def table():
    """{new words: row}, and {old words: new name} for every row whose name changed."""
    new = {words(r[0]): r for r in ROWS}
    old = {}
    for r in ROWS:
        if r[1] is not None:
            old[words(r[1])] = r[0]
    return new, old


def objects():
    """{object: [rows]} in table order: the groups of the listing."""
    out = {}
    for r in ROWS:
        out.setdefault(words(r[0])[0], []).append(r)
    return out


def refusal(argv):
    """The one line for an old name at the start of argv, or None when argv does not start with one."""
    _, old = table()
    for n in (3, 2, 1):
        key = tuple(argv[:n])
        if len(key) == n and key in old:
            return "fwx %s: now 'fwx %s'" % (" ".join(key), old[key])
    if len(argv) >= 2 and tuple(argv[:2]) in OLD_EXTRA:
        return "fwx %s: now %s" % (" ".join(argv[:2]), OLD_EXTRA[tuple(argv[:2])])
    if argv and argv[0] in OLD_OBJECTS:
        return "fwx %s: now 'fwx %s'" % (argv[0], OLD_OBJECTS[argv[0]])
    return None


def route(argv):
    """(module, handler argv) for argv without the leading `fwx`. None when the first word is no object; ("verb?", object) when
    the object is known and its verb is not, or it has no default and none was given; ("help", object) for `fwx OBJECT --help`."""
    new, _ = table()
    if not argv:
        return None
    obj, rest = argv[0], list(argv[1:])
    verbs = {w[1] for w in new if len(w) > 1 and w[0] == obj and not w[1].startswith("--")}
    lead = []
    while rest and (rest[0] in LEADING.get(obj, ()) or any(rest[0].startswith(o + "=") for o in LEADING.get(obj, ()))):
        n = 1 if "=" in rest[0] else 2  # `--project NAME` or `--project=NAME`
        lead += rest[:n]
        rest = rest[n:]
    if verbs and rest and rest[0] in ("-h", "--help", "help"):
        return "help", obj
    if rest and rest[0] in verbs:
        verb, rest = rest[0], rest[1:]
        row = new[(obj, verb)]
        for key, r in new.items():  # a row that needs a flag: `linear list --waiting`, `walk stop --orphans`
            if len(key) == 3 and key[:2] == (obj, verb) and key[2] in rest:
                rest.remove(key[2])
                row = r
                break
        return row[2], row[3] + lead + rest
    row = new.get((obj,)) or new.get((obj, DEFAULTS.get(obj, "")))
    if row is None:
        return ("verb?", obj) if verbs else None
    return row[2], row[3] + lead + rest


def shown(module, handler_argv):
    """The new name of the command a handler was started as, for the messages it writes: `phase new` for module `state` and
    [`new-phase`]; `walk capture` for `screenshot`. The module's own name when no row has it."""
    best = None
    for r in ROWS:
        n = len(r[3])
        if r[2] == module and list(handler_argv[:n]) == r[3] and (best is None or n > len(best[3])):
            best = r
    return best[0].split(" --")[0] if best else module.replace("_", "-")
