"""The naming rule of a `.fwx/` folder, and the check that reports a path outside it.

A path is good when it is a file of its level (names from `state`, the one owner of a phase's files) and no component of it holds an
upper-case letter or a space (the job key under `factory/` is a Linear key, written as it is). A bad path is reported as
`<path>: <reason>; belongs in <where>`.

  root of a scope (`.fwx/`, `subprojects/<name>/`)  project.md adr.tsv tree.excalidraw, research/ durable/ (any file),
                                                    milestones/vN/milestone.md, milestones/vN/phases/NN-slug/,
                                                    subprojects/<name>/ (the same inside), factory/<KEY>/ (a working folder)
  working folder (phase, subphase, factory job)     the files of `state.phase_paths`, research/ and demo/ (any file);
                                                    a closed or cancelled one also state.md and report-<n>.md
A subphase counts as closed when its enclosing phase is: `closing.md` writes `closed` on the phase folder only.

`check` reads each folder's audit file (through `state`) for the stages. As a module, `python3 -m fwx.layout [ROOT]` (with `lib/` on PYTHONPATH)
checks every file under ROOT (default `.fwx`), prints each bad path and how many it looked at, and exits 1 on a bad path or on
zero paths.
"""
import os
import re
import sys
from pathlib import Path

from fwx import state

SCOPE_FILES = ("project.md", "adr.tsv", "tree.excalidraw")
OPEN_FOLDERS = ("research", "durable")  # any lowercase file inside
_DIRS = ("research", "demo")
WORK_FILES = tuple(p.name for k, p in state.phase_paths(".").items() if k not in _DIRS)
_REPORT = re.compile(r"report-\d+\.md\Z")


def _exempt(parts, i):
    """Whether component i is a factory job key: `factory/<KEY>` at the root of a scope, however deep the subprojects nest."""
    j = 0
    while parts[j] == "subprojects" and j + 2 < len(parts):
        j += 2
    return i == j + 1 and parts[j] == "factory"


def _lowered(parts):
    return [c.replace(" ", "-") if _exempt(parts, i) else c.lower().replace(" ", "-") for i, c in enumerate(parts)]


def _closed(root, folder):
    return state.last_stage(root / folder) in state.CLOSED_STAGES


def _work(parts, closed):
    head = parts[0]
    if (head in _DIRS and len(parts) > 1) or (len(parts) == 1 and (head in WORK_FILES or (closed and (head == "state.md" or _REPORT.match(head))))):
        return None
    if len(parts) == 1 and (head == "state.md" or _REPORT.match(head)):
        return ("%s is kept only in a closed or cancelled phase" % head, "the phase, once it is closed or cancelled")
    return ("%s is not a file of a phase" % "/".join(parts), "research/%s of the phase" % "/".join(parts))


def _phase(root, folder, parts):
    if len(parts) >= 2 and state._SUBPHASE.match(parts[0]):
        return _work(parts[1:], _closed(root, folder) or _closed(root, folder / parts[0]))
    return _work(parts, _closed(root, folder))


def _milestone(root, folder, parts):
    if parts == ["milestone.md"]:
        return None
    if len(parts) >= 3 and parts[0] == "phases" and state._PHASE.match(parts[1]):
        return _phase(root, folder / "phases" / parts[1], parts[2:])
    return ("%s is not in a milestone" % "/".join(parts), "milestone.md, or phases/NN-slug/ of the milestone")


def _scope(root, folder, parts):
    head, rest = parts[0], parts[1:]
    if (head in SCOPE_FILES and not rest) or (head in OPEN_FOLDERS and rest):
        return None
    if head == "subprojects" and len(rest) >= 2:
        return _scope(root, folder / "subprojects" / rest[0], rest[1:])
    if head == "factory" and len(rest) >= 2:
        return _work(rest[1:], False)
    if head == "milestones" and len(rest) >= 2 and state._MILESTONE.match(rest[0]):
        return _milestone(root, folder / "milestones" / rest[0], rest[1:])
    return ("%s is not a file or folder of the root" % "/".join(parts), "research/%s, or milestones/vN/" % "/".join(parts))


def check(root, paths):
    """`(lines, looked)`: one `<path>: <reason>; belongs in <where>` line per bad path, and the number of paths looked at.
    A path is absolute or relative to `root`; one outside it raises ValueError."""
    root = Path(root)
    lines, looked = [], 0
    for p in paths:
        rel = os.path.relpath(os.path.join(str(root), str(p)), str(root))
        if rel == ".." or rel.startswith(".." + os.sep):
            raise ValueError("%s is outside %s" % (p, root))
        looked += 1
        parts = rel.split(os.sep)
        fixed = _lowered(parts)
        found = _scope(root, Path(), fixed)
        if fixed != parts:
            where = "/".join(fixed) if found is None else found[1]
            lines.append("%s: upper-case letter or space in a name; belongs in %s" % (rel, where))
        elif found:
            lines.append("%s: %s; belongs in %s" % (rel, found[0], found[1]))
    return lines, looked


def main(argv):
    root = argv[1] if len(argv) > 1 else state.PLAN_DIR
    paths = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
    lines, looked = check(root, paths)
    for line in lines:
        print(line)
    print("%d paths looked at" % looked)
    return 1 if lines or looked == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
