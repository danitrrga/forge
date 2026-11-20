"""The ledger of `outside` items (core.outside): fwx outside --part-dir D [--open] | add | route.

  fwx outside --part-dir D [--open]
      Prints `{"items": [...], "open": [ids]}` for the part folder D. Exit 0; with `--open` exit 1 when an item is open (neither fixed
      nor routed), so a script can ask "may this part close".
  fwx outside add --part-dir D --run R --items JSON
      Records a JSON list of items `{where, what, fix, size, fixed}` (the shape of principles.md rule 12), all or none. Prints
      `{"ids": [...], "demoted": [...]}`; `demoted` lists the items whose `fixed` commit is not on the branch in the current folder, recorded unfixed.
      Exit 0, 2 for a malformed item (the message names the item and the field) or a usage error.
  fwx outside route --part-dir D ID (--issue KEY | --task TASK)
      Marks item ID routed: to a Linear issue, its key recorded, or to a fix task. Exit 0, 2 for an unknown id, a key that is none or a usage error.

`fwx stage` refuses `reviewing`, `phase-review` and `closed` while an item of the phase or its subphases is open.
"""
import json
import os
import sys

from fwx import state
from fwx.core import outside

USAGES = {
    "list": "usage: fwx outside --part-dir D [--open]\n",
    "add": "usage: fwx outside add --part-dir D --run R --items JSON\n",
    "route": "usage: fwx outside route --part-dir D ID (--issue KEY | --task TASK)\n",
}


def _options(argv, valued, flags=()):
    """({option: value or True}, [words]) or None for an option nobody knows or a valued one with no value."""
    got, words, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in valued:
            if i + 1 >= len(argv):
                return None
            got[a] = argv[i + 1]
            i += 2
            continue
        if a in flags:
            got[a] = True
        elif a.startswith("-"):
            return None
        else:
            words.append(a)
        i += 1
    return got, words


def _list(argv):
    parsed = _options(argv, ("--part-dir",), ("--open",))
    if parsed is None or parsed[1] or "--part-dir" not in parsed[0]:
        sys.stderr.write(USAGES["list"])
        return 2
    got = parsed[0]
    folder = got["--part-dir"]
    if not os.path.isdir(folder):
        sys.stderr.write("fwx outside: %s is not a folder\n" % folder)
        return 2
    try:
        everything = outside.items(folder)
    except state.StateError as e:
        sys.stderr.write("fwx outside: %s\n" % e)
        return 2
    open_ids = [e["id"] for e in everything if outside.is_open(e)]
    print(json.dumps({"items": everything, "open": open_ids}))
    return 1 if "--open" in got and open_ids else 0


def _add(argv):
    parsed = _options(argv, ("--part-dir", "--run", "--items"))
    if parsed is None or parsed[1] or any(k not in parsed[0] for k in ("--part-dir", "--run", "--items")):
        sys.stderr.write(USAGES["add"])
        return 2
    got = parsed[0]
    try:
        batch = json.loads(got["--items"])
    except ValueError as e:
        sys.stderr.write("fwx outside add: --items is not JSON: %s\n" % e)
        return 2
    if not isinstance(batch, list):
        sys.stderr.write("fwx outside add: --items is a JSON list of items\n")
        return 2
    if not os.path.isdir(got["--part-dir"]):
        sys.stderr.write("fwx outside add: %s is not a folder\n" % got["--part-dir"])
        return 2
    try:
        ids, demoted = outside.add(got["--part-dir"], batch, got["--run"], os.getcwd())
    except state.StateError as e:
        sys.stderr.write("fwx outside add: %s\n" % e)
        return 2
    print(json.dumps({"ids": ids, "demoted": demoted}))
    return 0


def _route(argv):
    parsed = _options(argv, ("--part-dir", "--issue", "--task"))
    if parsed is None or len(parsed[1]) != 1 or "--part-dir" not in parsed[0]:
        sys.stderr.write(USAGES["route"])
        return 2
    got = parsed[0]
    try:
        entry = outside.route(got["--part-dir"], parsed[1][0], got.get("--issue"), got.get("--task"))
    except state.StateError as e:
        sys.stderr.write("fwx outside route: %s\n" % e)
        return 2
    print(json.dumps(entry))
    return 0


def main(argv):
    if argv and argv[0] == "add":
        return _add(argv[1:])
    if argv and argv[0] == "route":
        return _route(argv[1:])
    if argv and argv[0] == "list":
        return _list(argv[1:])
    sys.stderr.write(USAGES["list"] + USAGES["add"] + USAGES["route"])
    return 2
