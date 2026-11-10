#!/usr/bin/env python3
"""`fwx playbooks check` without the tree (lib/fwx/playbooks.py): the block format of every playbook and what
the blocks say to each other, on a toy playbook of five nodes and a toy scope.tsv. The tree is the owner's drawing in
private data, so what compares a block with it is tests/test_playbooks_tree.py.

Seen red before lib/fwx/playbooks.py existed (the whole file):
  FAIL: cannot import fwx.playbooks: cannot import name 'playbooks' from 'fwx' (.../lib/fwx/__init__.py)

Each control is the good toy with one change and must fail with the message the checker gives for it. The toy passes
first (a checker that never passes is not evidence either); each row of CASES below is one control.

Seen red, each on a copy of lib/fwx/playbooks.py with that one check switched off (`if <check>:` made `if False:`), the
first FAIL line each gave (`got []` where the check is the only one that says it):
  an id repeated, a field missing, a model named, a stage that does not exist, a stage jump, two writers of state.md,
  a block outside its playbook, a destination outside scope.tsv, a scope row with no block, no Version, a role outside
  config.ROLES, a Who outside the list, an exit type outside the five, an Invokes outside the list, the same exit twice:
      FAIL: control: <its label>: got []
  Exits none beside a list: FAIL: control: Exits none beside a list of exits: got []
  the audit.tsv exemption removed:  FAIL: audit.tsv may be written by every block: ... got ["audit.tsv is written by n_b and by n_d: ...
  a Writes `nothing, state.md` (form check off): FAIL: control: nothing mixed with a file: got ["state.md is written by ...
  code fences read as blocks:  FAIL: a block inside a code fence does not count (the id is not twice): got ([...appears in two blocks...], 6), want ([], 5)
  the exit 77 without a tree: FAIL: with no tree the tree checks are said not to have run, exit 77: got (False, 0), want (False, 77)
  NOT CHECKED not printed:    FAIL: a playbook that has no file is NOT CHECKED with its row count: got [], want ['NOT CHECKED: 2 nodes of execute ...']
  NOT RUN not printed:        FAIL: --only execute looks at the file that is not there: ...
  --only not filtering:       FAIL: --only keeps to one playbook: the problem of the other is not shown: 1 'FAIL: session.md:14 n_b has Stage nosuchstage ...
The `is a stage jump` toy first used discuss -> planning and stayed green: the factory machine allows it. discuss ->
postmortem is allowed by neither, which is what the control needs.
"""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
try:
    from fwx import playbooks  # noqa: E402
except ImportError as e:
    print("FAIL: cannot import fwx.playbooks: %s" % e)
    sys.exit(1)

s = helpers.Suite()
ENV = {"PYTHONDONTWRITEBYTECODE": "1"}

# five nodes of the supervised session; n_d loops back to n_c, n_e is a block on an arrow (no stage)
GOOD = [
    dict(id="n_a", title="Alex opens a chat", who="owner", stage="discuss", writes="nothing", invokes="nothing",
         exits=[("to", "n_b", "Alex asks")]),
    dict(id="n_b", title="The orchestrator decides", who="orchestrator", stage="premortem", writes="state.md",
         invokes="skill grilling", exits=[("to", "n_c", "the plan is wanted")]),
    dict(id="n_c", title="A planner writes the plan", who="agent planner", stage="planning", writes="plan.md",
         invokes="nothing", exits=[("to", "n_d", "the plan is written")]),
    dict(id="n_d", title="The checks run", who="script `fwx verify`", stage="postmortem", writes="audit.tsv",
         invokes="command `fwx verify`", exits=[("loop", "n_c", "a check fails"), ("sometimes", "n_e", "a blocker")]),
    dict(id="n_e", title="A block on an arrow", who="orchestrator", stage="-", writes="nothing", invokes="nothing",
         exits=[]),
]
SCOPE = {"n_a": "session", "n_b": "session", "n_c": "session", "n_d": "session", "n_e": "session",
         "n_f": "execute", "n_g": "execute"}
RULES = ["review-label", "ci-failed", "still-running"]


def render(b):
    out = ["### %s · %s" % (b["id"], b["title"])]
    for field, key in (("Who", "who"), ("Stage", "stage"), ("Writes", "writes"), ("Invokes", "invokes")):
        if b.get(key) is not None:
            out.append("- **%s:** %s" % (field, b[key]))
    out.append("- **Does:** %s" % b.get("does", "Does one thing in one sentence."))
    if b["exits"]:
        out.append("- **Exits:**")
        out += ["  - %s %s: %s" % e for e in b["exits"]]
    else:
        out.append("- **Exits:** none")
    if b.get("why"):
        out.append("- **Why:** %s" % b["why"])
    return "\n".join(out) + "\n"


def doc(blocks, title="# Session", version="Version: 1"):
    return title + "\n\n" + (version + "\n\n" if version else "") + "\n".join(render(b) for b in blocks)


def world(files, scope=SCOPE, extra=None):
    """A playbooks dir with scope.tsv and the given {name: text}; returns the dir."""
    d = helpers.mkdtemp("fwx-pb-")
    helpers.write(d, "scope.tsv", "".join("%s\t%s\n" % kv for kv in scope.items()))
    for name, text in files.items():
        helpers.write(d, name + ".md", text)
    for name, text in (extra or {}).items():
        helpers.write(d, name, text)
    return d


def rules_file():
    d = helpers.mkdtemp("fwx-rules-")
    return helpers.write(d, "decide_rules.json", json.dumps({"rules": [{"id": r} for r in RULES]}))


def run(d, **kw):
    return playbooks.check(d, rules_path=rules_file(), **kw)


def good():
    return copy.deepcopy(GOOD)


def has(report, *needles):
    return any(all(n in e for n in needles) for e in report.errors)


def control(label, files, *needles, scope=SCOPE, extra=None):
    r = run(world(files, scope, extra))
    s.ok("control: %s" % label, has(r, *needles), "got %r" % r.errors)


# ---- the good toy passes, and says how much it looked at
r = run(world({"session": doc(good())}))
s.eq("the good toy has no problem", r.errors, [])
s.eq("it compared five blocks", r.blocks, 5)
s.eq("no tree: no arrow compared", r.arrows, 0)
s.eq("a playbook that has no file is NOT CHECKED with its row count",
     r.not_checked, ["NOT CHECKED: 2 nodes of execute (playbook not written yet)"])
s.eq("with no tree the tree checks are said not to have run, exit 77", (r.tree_ran, r.exit_code), (False, 77))

# ---- one change each
b = good()
b[3]["id"] = "n_c"
control("an id repeated", {"session": doc(b)}, "n_c", "appears in two blocks")

b = good()
b[2]["stage"] = None
control("a field missing", {"session": doc(b)}, "n_c lacks the field Stage")

b = good()
b[1]["does"] = "Asks the sonnet agent to plan."
control("a model named", {"session": doc(b)}, "names a model", "sonnet")

b = good()
b[1]["stage"] = "nosuchstage"
control("a stage that does not exist", {"session": doc(b)}, "n_b", "nosuchstage", "not a stage")

b = good()
b[0]["exits"] = [("to", "n_d", "skips the planning")]
control("a stage jump the table does not allow", {"session": doc(b)}, "n_a", "discuss", "postmortem",
        "data/stages.json allows no discuss -> postmortem")

b = good()
b[1]["writes"] = "state.md"
b[2]["writes"] = "state.md, plan.md"
control("two writers of state.md", {"session": doc(b)}, "state.md", "n_b", "n_c", "one block writes")

b = good()
s_ = dict(SCOPE, n_e="execute")
control("a block outside its playbook", {"session": doc(b)}, "n_e", "scope.tsv assigns it to execute", scope=s_)

b = good()
b[0]["exits"] = [("to", "n_zzz", "typo")]
control("a destination outside scope.tsv", {"session": doc(b)}, "n_a", "n_zzz", "not in scope.tsv")

# the same controls with the other playbook's file written: the real ones the generator checks
control("a scope row with no block", {"session": doc(good()[:4])}, "n_e", "has no block")
control("no Version line", {"session": doc(good(), version=None)}, "session.md", "Version")
control("a Version that is not a number", {"session": doc(good(), version="Version: two")}, "session.md", "Version")
b = good()
b[2]["who"] = "agent nosuchrole"
control("a role outside config.ROLES", {"session": doc(b)}, "n_c", "nosuchrole", "role")
b = good()
b[2]["who"] = "robot"
control("a Who outside the list", {"session": doc(b)}, "n_c", "Who", "robot")
b = good()
b[3]["exits"][0] = ("maybe", "n_c", "a check fails")
control("an exit type outside the five", {"session": doc(b)}, "n_d", "maybe")
b = good()
b[3]["exits"] = b[3]["exits"] + [("loop", "n_c", "twice")]
control("the same exit twice", {"session": doc(b)}, "n_d", "n_c", "twice")
b = good()
b[2]["invokes"] = "magic spell"
control("an Invokes outside the list", {"session": doc(b)}, "n_c", "Invokes", "magic spell")
b = good()
b[0]["writes"] = "nothing, state.md"
control("nothing mixed with a file", {"session": doc(b)}, "n_a", "Writes", "nothing")
b = good()
b[2]["stage"] = None
b[2]["who"] = None
control("the missing fields are all listed: Who", {"session": doc(b)}, "n_c lacks the field Who")
control("the missing fields are all listed: Stage", {"session": doc(b)}, "n_c lacks the field Stage")
control("a connector has no block", {"session": doc(good())}, "n_e", "connector", scope=dict(SCOPE, n_e="connector"))
control("a model name in any playbooks/*.md, style.md too", {"session": doc(good())}, "style.md", "names a model", "Haiku",
        extra={"style.md": "# Style\n\nUse Haiku for lookups.\n"})
control("an exit written with no condition", {"session": doc(good()).replace("Alex asks", "")}, "n_a", "exit")
b = good()
b[4]["exits"] = [("to", "n_a", "back")]
control("Exits none beside a list of exits", {"session": doc(b).replace("  - to n_a: back", "  - to n_a: back").replace(
    "- **Exits:**\n  - to n_a: back", "- **Exits:** none\n  - to n_a: back")}, "n_e", "Exits none", "lists exits")
control("an Exits line with prose", {"session": doc(good()).replace("- **Exits:** none", "- **Exits:** nowhere")}, "n_e", "Exits")

# ---- what must not fail
r = run(world({"session": doc(good())}, extra={"style.md": "# Style\n\nColours.\n", "principles.md": "# Principles\n"}))
s.eq("style.md and principles.md without blocks are no playbooks and no problem", (r.errors, r.blocks), ([], 5))

b = good()
b[3]["exits"] = [("loop", "n_c", "a check fails"), ("sometimes", "n_e", "a blocker")]
b[1]["writes"] = "audit.tsv"
r = run(world({"session": doc(b)}))
s.eq("audit.tsv may be written by every block: state.append_audit writes it for all", r.errors, [])

b = good()
b[0]["why"] = "Because the owner decides."
r = run(world({"session": doc(b)}))
s.eq("Why is optional and allowed", r.errors, [])

b = good()
b[2]["who"] = "agent planner, researcher"
r = run(world({"session": doc(b)}))
s.eq("an agent with two roles", r.errors, [])

r = run(world({"session": doc(good())}), only="execute")
s.ok("--only execute looks at the file that is not there", r.blocks == 0 and r.exit_code == 77
     and any("NOT RUN, NOT ARMED: no playbook has nodes yet" in l for l in r.lines()), "got %r %r" % (r.blocks, r.lines()))

# a block in a code fence is an example, not a block
fenced = "# Session\n\nVersion: 1\n\n```markdown\n" + render(GOOD[0]) + "```\n\n" + "\n".join(render(x) for x in GOOD)
r = run(world({"session": fenced}))
s.eq("a block inside a code fence does not count (the id is not twice)", (r.errors, r.blocks), ([], 5))

# ---- no playbook with nodes: NOT RUN, and a draft that has a file but no blocks is a problem
r = run(world({}))
s.eq("no playbook file at all: nothing compared, exit 77", (r.blocks, r.exit_code), (0, 77))
s.ok("... and it says NOT RUN, NOT ARMED: no playbook has nodes yet",
     "NOT RUN, NOT ARMED: no playbook has nodes yet" in r.lines(), "got %r" % r.lines())
s.eq("... and a NOT CHECKED line for each playbook of scope.tsv", len(r.not_checked), 2)
r = run(world({"session": "# Session\n\nVersion: 1\n"}))
s.ok("a file with a Version and no block is a problem", has(r, "session.md", "no block"), "got %r" % r.errors)

# ---- the command, in a copy of the code with a toy playbooks dir
code = helpers.mkdtemp("fwx-code-")
for top in ("bin", "lib", "data"):
    shutil.copytree(os.path.join(helpers.ROOT, top), os.path.join(code, top),
                    ignore=shutil.ignore_patterns("__pycache__"))
helpers.write(code, "playbooks/scope.tsv", "".join("%s\t%s\n" % kv for kv in SCOPE.items()))


repo = helpers.toy_repo()  # the command reads paths.tree of the repo it runs in


def cli(*args, cwd=None):
    import subprocess
    return subprocess.run([sys.executable, os.path.join(code, "bin", "fwx"), "playbooks"] + list(args),
                          cwd=cwd or repo, env=helpers.clean_env(**ENV), capture_output=True, text=True)


r = cli("check")
s.ok("check with no playbook and no tree: NOT RUN and exit 77",
     r.returncode == 77 and "NOT RUN, NOT ARMED: no playbook has nodes yet" in r.stdout
     and "NOT CHECKED: 5 nodes of session (playbook not written yet)" in r.stdout, "%s %r" % (r.returncode, r.stdout))
helpers.write(code, "playbooks/session.md", doc(good()))
r = cli("check")
s.ok("check with one playbook and no tree: it ran what it could, exit 77, and says what it looked at",
     r.returncode == 77 and "5 blocks" in r.stdout and "no tree" in r.stdout and "NOT RUN, NOT ARMED" in r.stdout
     and "NOT CHECKED: 2 nodes of execute" in r.stdout, "%s %r" % (r.returncode, r.stdout))
b = good()
b[1]["stage"] = "nosuchstage"
helpers.write(code, "playbooks/session.md", doc(b))
r = cli("check")
s.ok("check with a problem exits 1 and prints it", r.returncode == 1 and "nosuchstage" in r.stdout, "%s %r" % (r.returncode, r.stdout))
r = cli("check", "--only", "execute")
s.ok("--only keeps to one playbook: the problem of the other is not shown",
     r.returncode == 77 and "nosuchstage" not in r.stdout, "%s %r" % (r.returncode, r.stdout))
r = cli("check", "--only", "session")
s.ok("--only session shows the problem of session", r.returncode == 1 and "nosuchstage" in r.stdout, "%s %r" % (r.returncode, r.stdout))
for args, label in ((["check", "--only", "nosuch"], "an unknown playbook"), (["check", "--only"], "--only with no value"),
                    (["check", "extra"], "a stray argument"), (["check", "--tree", os.path.join(code, "absent")], "a tree that is not there")):
    r = cli(*args)
    s.ok("check %s: exit 2, a message, no traceback" % label, r.returncode == 2 and r.stderr and "Traceback" not in r.stderr,
         "%s %r" % (r.returncode, r.stderr))
r = cli("check", "--only", "nosuch")
s.ok("check --only nosuch names the valid playbooks", "session" in r.stderr and "execute" in r.stderr, r.stderr)

s.done()
