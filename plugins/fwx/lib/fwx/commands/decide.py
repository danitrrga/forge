"""The merge decision for the facts of a PR: fwx decide --facts FILE.

Reads FILE (the facts of a PR, JSON, the contract of core.decide) and prints one JSON object
`{"decision": "merge|handover|pending", "would_merge": bool, "reasons": ["<rule id>: <text>", ...]}`. Exit 0 with a decision,
whatever it is; 2 for a usage error, a file that cannot be read or is not JSON, facts that are not the contract's (the error
names the path of the field) or a rule table that cannot be used, with the error on stderr and nothing on stdout.
"""
import json
import sys

from fwx.core import decide

USAGE = "usage: fwx decide --facts FILE\n"


def main(argv):
    if len(argv) != 2 or argv[0] != "--facts" or argv[1].startswith("-"):
        sys.stderr.write(USAGE)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as fh:
            facts = json.load(fh)
    except OSError as e:
        sys.stderr.write("fwx decide: cannot read %s: %s\n" % (argv[1], e.strerror or e))
        return 2
    except ValueError as e:
        sys.stderr.write("fwx decide: %s is not JSON: %s\n" % (argv[1], e))
        return 2
    try:
        result = decide.decide(facts)
    except (decide.FactsError, decide.TableError) as e:
        sys.stderr.write("fwx decide: %s\n" % e)
        return 2
    print(json.dumps(result, indent=2))
    return 0
