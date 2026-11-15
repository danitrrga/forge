#!/usr/bin/env python3
"""`fwx session --json` carries what a status chip needs: `project`, `stage`, `part`, `parts` and `branch`, added to the
keys `state.resolve` already gave (those are unchanged), read from the phase's audit.tsv.

Rules the test holds: `project` is the `project.name` of `.claude/fwx.json` and null where that file is missing; `stage` is the
phase's last stage row, read as `fwx phase list` reads it; `part` is N of the last stage row whose detail says `part <N>`
and `parts` is the number of subphases, or 1 (both null when no stage row names a part); `branch` is B of the last stage row whose detail says `branch <B>` (the row of
`reviewing part 1` does not repeat it); with no phase every new key is null.

Seen red on master before the keys existed (a toy repo whose phase has `executing part 1 branch fwx/x`):
  FAIL: executing part 1 of 2: project, stage, part, parts, branch: got ('MISSING', 'MISSING', 'MISSING', 'MISSING', 'MISSING'), want ('toy', 'executing', 1, 2, 'fwx/x')
  (8 of 14 checks failed)
Control, `part` read from the first stage row instead of the last (`if part and out["part"] is None`), seen red:
  FAIL: a later row `executing part 2 corrections`: part and branch: got (1, 'fwx/x'), want (2, 'fwx/x')
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, "lib"))
from fwx import state  # noqa: E402

s = helpers.Suite()
ENV = {"CLAUDE_CODE_SESSION_ID": "sess-sum"}
NEW = ("project", "stage", "part", "parts", "branch")
SHA = "a" * 40


def session(repo):
    r = helpers.fwx(repo, "session", "--json", env=ENV)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        s.ok("session --json prints JSON in %s" % os.path.basename(repo), False, r.stdout + r.stderr)
        return r.returncode, {}


def new_keys(got):
    return tuple(got.get(k, "MISSING") for k in NEW)


def stage(phase, detail):
    state.append_audit(phase, "stage", detail, sha=SHA)


FILES = {"README": "toy\n", ".gitignore": ".fwx/\n", ".claude/fwx.json": json.dumps({"project": {"name": "toy"}})}

# ---- no phase: the new keys are null, the old ones are state.resolve's, byte for byte -------------------------------
repo = helpers.toy_repo(FILES)
rc, got = session(repo)
s.eq("no phase: exit code 1 as before", rc, 1)
s.eq("no phase: project is the configured name, the rest null", new_keys(got), ("toy", None, None, None, None))
old = {k: v for k, v in got.items() if k not in NEW}
s.eq("no phase: the old keys are what state.resolve returns", old, state.resolve(repo, session="sess-sum"))

# ---- a phase at executing, part 1 of 2 --------------------------------------------------------------------------------
r = helpers.fwx(repo, "phase", "new", "alpha", env=ENV)
phase = r.stdout.strip()
state.new_subphase(phase, "first")
state.new_subphase(phase, "second")
rc, got = session(repo)
s.eq("a phase with no stage row: nothing names a part, so stage, part, parts and branch are null", new_keys(got), ("toy", None, None, None, None))
stage(phase, "executing part 1 branch fwx/x")
rc, got = session(repo)
s.eq("executing part 1 of 2: project, stage, part, parts, branch", new_keys(got), ("toy", "executing", 1, 2, "fwx/x"))
s.eq("executing part 1 of 2: exit code", rc, 0)
s.eq("executing part 1 of 2: the old keys are state.resolve's", {k: v for k, v in got.items() if k not in NEW},
     state.resolve(repo, session="sess-sum"))
stage(phase, "reviewing part 1")
rc, got = session(repo)
s.eq("a row that names no branch: the branch of the earlier row stays", new_keys(got), ("toy", "reviewing", 1, 2, "fwx/x"))
stage(phase, "executing part 2 corrections")
rc, got = session(repo)
s.eq("a later row `executing part 2 corrections`: part and branch", (got.get("part"), got.get("branch")), (2, "fwx/x"))
stage(phase, "closing")
rc, got = session(repo)
s.eq("a last row with no part: stage moves on, the last part named stays", (got.get("stage"), got.get("part")), ("closing", 2))

# ---- no subphases: parts is 1 -------------------------------------------------------------------------------------------
one = helpers.toy_repo(FILES)
p1 = helpers.fwx(one, "phase", "new", "solo", env=ENV).stdout.strip()
stage(p1, "executing part 1 branch fwx/solo")
rc, got = session(one)
s.eq("no subphases: parts is 1", new_keys(got), ("toy", "executing", 1, 1, "fwx/solo"))

# ---- no .claude/fwx.json: project is null (the chip hides) --------------------------------------------------------------
bare = helpers.toy_repo({"README": "toy\n", ".gitignore": ".fwx/\n"})
helpers.fwx(bare, "phase", "new", "x", env=ENV)
rc, got = session(bare)
s.eq("no .claude/fwx.json: project is null", got.get("project", "MISSING"), None)

# ---- outside a repository: still exit 2, no traceback --------------------------------------------------------------------
nogit = helpers.mkdtemp("fwx-nogit-")
r = helpers.fwx(nogit, "session", "--json", env=ENV)
s.eq("outside a repository: exit code 2", r.returncode, 2)
s.ok("outside a repository: no traceback", "Traceback" not in r.stderr, r.stderr[-300:])

s.done()
