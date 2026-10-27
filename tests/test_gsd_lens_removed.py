#!/usr/bin/env python3
"""The three lens skills (musk, cut-the-ceremony, boil-the-ocean) are gone, and a copy that comes back is an error.

forge-authored skills have no upstream file, so scripts/sync/sync_gsd_runtime.py never regenerates them and
FORGE_AUTHORED is what keeps `--skills` from flagging them. Dropping the three names from that set is what makes a
stray copy of one fail the check, which is the guard against the removal being undone by accident.

The script is loaded as a module with HOME on a toy dir, as in tests/test_gsd_spike_freeform.py: nothing is written
to the real HOME, and the toy skills dir and staging dir are made here.

Seen failing on 972195a, before the names left FORGE_AUTHORED:
  "1 FORGE_AUTHORED: only gsd-sketch is forge-authored, got ['gsd-boil-the-ocean', 'gsd-cut-the-ceremony', 'gsd-musk', 'gsd-sketch']"
  "2 a leftover gsd-musk is an error: errors [\"gsd-execute-phase: it is not in the staged package, so patch ... applies to nothing ...\", ...]"
  (the toy staging holds no package skills, so only the unrelated patch-target errors are there)
Negative control: putting "gsd-musk" back into FORGE_AUTHORED in a backup copy of the script makes both fail again;
restored from the backup, 0 failures.
"""
import importlib.util
import io
import os
import sys
from contextlib import redirect_stdout

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FORGE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sandbox  # noqa: E402

TOY = sandbox.mkdtemp("gsd-lens-removed-test-")
os.environ["HOME"] = os.path.join(TOY, "home")
os.makedirs(os.environ["HOME"])
for var in ("CLAUDE_PROJECT_DIR", "FORGE_WRITE_LOG"):
    os.environ.pop(var, None)
sys.argv = [sys.argv[0]]
_spec = importlib.util.spec_from_file_location(
    "sync_gsd_runtime", os.path.join(FORGE, "scripts", "sync", "sync_gsd_runtime.py"))
gsd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gsd)

failures = []


def want(label, ok, detail=""):
    if not ok:
        failures.append("%s%s" % (label, (": " + detail) if detail else ""))


want("1 FORGE_AUTHORED: only gsd-sketch is forge-authored", gsd.FORGE_AUTHORED == {"gsd-sketch"},
     "got %s" % sorted(gsd.FORGE_AUTHORED))

skills = os.path.join(TOY, "skills")
stage = os.path.join(TOY, "stage")
os.makedirs(os.path.join(skills, "gsd-musk"))
os.makedirs(os.path.join(stage, "skills"))
gsd.FORGE_SKILLS, gsd.STAGE = skills, stage
errors = []
with redirect_stdout(io.StringIO()):
    gsd.sync_skills(errors)
want("2 a leftover gsd-musk is an error", "skill without upstream counterpart: gsd-musk" in errors, "errors %s" % errors)

sandbox.cleanup(bool(failures))
for f in failures:
    print("FAIL", f)
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
