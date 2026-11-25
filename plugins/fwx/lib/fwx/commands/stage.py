"""Change the stage of a phase or a factory job, only if data/stages.json allows it: fwx stage <dir> <stage> [--why TEXT].

`<dir>` is a phase, a subphase or a job folder (`.fwx/factory/<KEY>/`); its machine follows the path. A legal change adds a
`stage` row through state.append_audit (the target stage and the why, at the HEAD of the folder) and prints
`<from> -> <to>`. Exit 0 on a change, 1 when the table refuses it (the message names both stages and the machine, and no
row is written), 2 for a usage error or a folder or table that cannot be used. After a change it refreshes the base-context
file of the folder, or of its phase for a subphase, whose `context.md` is the phase's (context_base.refresh); when that fails, `fwx stage: context-base: <reason>` goes to stderr and the exit
stays 0.
"""
import os
import sys

from fwx import context_base, state
from fwx.core import stages

USAGE = "usage: fwx stage <dir> <stage> [--why TEXT]\n"


def main(argv):
    args, why = list(argv), ""
    if "--why" in args:
        i = args.index("--why")
        if i + 1 >= len(args):
            sys.stderr.write(USAGE)
            return 2
        why = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2 or any(a.startswith("-") for a in args):
        sys.stderr.write(USAGE)
        return 2
    folder, to = args
    try:
        frm = stages.advance(folder, to, why)
    except stages.Refused as e:
        sys.stderr.write("fwx stage: %s\n" % e)
        return 1
    except state.StateError as e:
        sys.stderr.write("fwx stage: %s\n" % e)
        return 2
    try:  # the change is made and recorded: a base that cannot be rebuilt is a line on stderr, never another exit code
        p = os.path.abspath(folder)
        nested = state._SUBPHASE.match(os.path.basename(p)) and state._PHASE.match(os.path.basename(os.path.dirname(p)))
        context_base.refresh(os.path.dirname(p) if nested else folder)
    except Exception as e:
        sys.stderr.write("fwx stage: context-base: %s\n" % e)
    print("%s -> %s" % (frm, to))
    return 0
