"""The verb-first names of the fwx commands: `fwx <verb> <noun>`, and the command of today each one reaches.

This is the ONE table. Every row is (verb-first name, today's command), both written as the words typed after `fwx`:
`("find phase", "state resolve")` makes `fwx find phase ...` run what `fwx state resolve ...` runs, with the same
arguments after it. The names are PROPOSED: changing one is editing its row here and nothing else; the tests read the
names from this table and spell none.

A command that does not need a row is listed apart: UNCHANGED keeps its name, GONE is deleted by a later unit and gets no
verb-first name. A new command does not come here at all: a file `commands/<verb>_<noun>.py` runs as `fwx <verb> <noun>`.

Not yet rows, because the commands are not in this tree (the checks of tests/test_cli.py fail on a row for a command that
does not exist, and on a command with no row, so the unit that adds them adds their rows): from the UI walk,
walk up|down|ab|pw|capacity|arm-control|findings|review-page|review-answers|sweep|selftest are proposed as
start walk, stop walk, browse ab, browse pw, check walk, arm control, show findings, build review, read review, sweep walk,
selftest walk, and screenshot as take screenshot.

Importing this module imports nothing: bin/fwx loads it only when a name is not a command of its own.
"""

ROWS = (
    ("show budget", "budget"),
    ("check capacity", "capacity"),
    ("show model", "model"),
    ("show statusline", "statusline"),
    ("count rounds", "rounds"),
    ("set stage", "stage"),
    ("start discuss", "discuss start"),

    ("build context", "context-base build"),
    ("seal context", "context-base seal"),
    ("check context", "context-base check"),
    ("audit context", "context-base audit"),

    ("list issues", "linear list"),
    ("list waiting", "linear waiting"),
    ("comment issue", "linear comment"),
    ("label issue", "linear label"),
    ("create issue", "linear create"),

    ("check plan", "plan check"),
    ("brief plan", "plan brief"),
    ("status plan", "plan status"),
    ("show tree", "playbooks tree"),
    ("check playbooks", "playbooks check"),

    ("find phase", "state resolve"),
    ("list phases", "state list"),
    ("use phase", "state use"),
    ("new phase", "state new-phase"),
    ("new subphase", "state new-subphase"),
    ("new milestone", "state new-milestone"),
    ("cancel phase", "state cancel"),
    ("record decision", "state decision"),
    ("list decisions", "state decisions"),
    ("check state", "state check"),

    ("prepare wave", "wave prepare"),
    ("check base", "wave check-base"),
    ("make scratch", "wave scratch"),
    ("integrate wave", "wave integrate"),
    ("fix round", "wave fix-round"),
    ("revert wave", "wave revert"),
    ("clean wave", "wave cleanup"),
    ("show wave", "wave summary"),
)

UNCHANGED = ("decide", "verify")
GONE = ("test",)


def today():
    """Every command of today the table covers: the rows' old column, UNCHANGED and GONE."""
    return [old for _, old in ROWS] + list(UNCHANGED) + list(GONE)


def lookup(name, rows=ROWS):
    """The words of today's command a verb-first name stands for ("find phase" -> ["state", "resolve"]), or None."""
    for new, old in rows:
        if new == name:
            return old.split()
    return None


def verbs(rows=ROWS):
    """{verb: [noun, ...]} in the order the table gives them, for the listing of `fwx help`."""
    out = {}
    for new, _ in rows:
        verb, noun = new.split()
        out.setdefault(verb, []).append(noun)
    return out
