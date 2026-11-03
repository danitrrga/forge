"""Count a job's implement-verify rounds against the cap: fwx rounds <dir> [--use MOTIVE | --reset MOTIVE].

`<dir>` is a job folder (`.fwx/factory/<KEY>/`) or a phase folder; the rounds come from its audit rows (core.rounds says
what a round is). The cap is `rounds` in the configuration (default 3), per job and for every change the factory makes.
`--use` spends a round without a red evidence row (a wave that would not merge, a real review finding, a walk fix);
`--reset` restarts the count (a fix by the owner). Both write one `round` row through state.append_audit, need a motive and
exclude each other. Prints `rounds <used>/<cap>` after any write. Exit 0 with a round left, 1 when the cap is spent, 2 for
a usage error, a folder with nothing to count or a configuration that cannot be used.
"""
import sys

from fwx import config, state
from fwx.core import rounds

USAGE = 'usage: fwx rounds <dir> [--use "<motive>" | --reset "<motive>"]\n'


def main(argv):
    args, option = list(argv), None
    for flag in ("--use", "--reset"):
        while flag in args:
            i = args.index(flag)
            if option is not None or i + 1 >= len(args) or not args[i + 1].strip() or args[i + 1].startswith("-"):
                sys.stderr.write("fwx rounds: %s\n%s" % ("--use and --reset exclude each other, each once"
                                                          if option is not None else "%s needs a motive" % flag, USAGE))
                return 2
            option = (flag[2:], args[i + 1])
            del args[i:i + 2]
    if len(args) != 1 or args[0].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    folder = args[0]
    try:
        if option:
            rounds.record(folder, *option)
        used, limit = rounds.status(folder)
    except (state.StateError, config.ConfigError) as e:
        sys.stderr.write("fwx rounds: %s\n" % e)
        return 2
    print("rounds %d/%d" % (used, limit))
    return 1 if used >= limit else 0
