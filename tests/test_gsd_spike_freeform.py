#!/usr/bin/env python3
"""The forge free-form block on gsd-spike: the workflow is run by the main agent, the owner steers it, and only the
state other GSD commands read back (each spike's README verdict, MANIFEST.md) and the commit stay mandatory.

It is two patches in scripts/sync/sync_gsd_runtime.py, because a forge edit to a gsd-* file only survives as a patch:
an ENGINE_PATCHES entry for workflows/spike.md (the block, config/gsd/spike-freeform.md, put right after the first line
of the file, whose exact text is the anchor) and a SKILL_PATCHES entry for gsd-spike that replaces the sentence
"Preserve all workflow gates (...)".

The script is loaded as a module with HOME on a toy dir, as in scripts/sync/test_sync_gsd_runtime.py: nothing is written
to the real HOME. The real staged spike.md and SKILL.md under the real ~/.cache/forge/gsd-stage are only read (case 3
and the last part of case 4); with no staging, or one that no longer holds them, those parts say NOT RUN, NOT ARMED.

Seen failing on a59e67d, before the patches existed:
  "1 engine entry: workflows/spike.md is not a key of ENGINE_PATCHES (keys ['references/mandatory-initial-read.md', ...])"
  "4 skill entry: gsd-spike is not a key of SKILL_PATCHES (keys ['gsd-execute-phase', 'gsd-update'])"
and, because the cases after them have nothing to apply, "2 fixture: no engine entry with a payload file to apply" and
"3 staged spike.md: no engine entry with a payload file to apply".
Negative control, on the finished code: the workflows/spike.md entry removed from a backup copy of
sync_gsd_runtime.py makes case 1 fail with the message above (cases 2 and 3 with it); restored from the backup."""
import importlib.util
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FORGE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import sandbox  # noqa: E402

REAL_HOME = os.path.expanduser("~")  # read before the toy HOME replaces it; only the staged files are read from it
TOY = sandbox.mkdtemp("gsd-spike-freeform-test-")
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
ANCHOR = "<purpose>"
SENTENCE_START = "Preserve all workflow gates ("
STAGE = os.path.join(REAL_HOME, ".cache", "forge", "gsd-stage", "cfg")
# the workflow steps the block overrides: each must be named in it and must exist upstream
STEPS = ("frontier_mode", "decompose", "align", "research", "build_spikes", "create_manifest")


def want(label, ok, detail=""):
    if not ok:
        failures.append("%s%s" % (label, (": " + detail) if detail else ""))


def patched(text, name, patches):
    errors = []
    return gsd.apply_patches(text, name, patches, errors), errors


def read_real(rel):
    p = os.path.join(STAGE, rel)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return fh.read()


# 1. the engine entry and its payload file
eng = gsd.ENGINE_PATCHES.get("workflows/spike.md")
block = None
if eng is None:
    failures.append("1 engine entry: workflows/spike.md is not a key of ENGINE_PATCHES (keys %s)" % sorted(gsd.ENGINE_PATCHES))
else:
    want("1 engine entry: exactly one replace patch", len(eng) == 1 and eng[0][1] == "replace", repr([p[:2] for p in eng]))
    pid, op, anchor, payload = eng[0]
    want("1 engine entry: the anchor is the exact first line of the file", anchor == ANCHOR, repr(anchor))
    want("1 engine entry: the payload is a file: of config/gsd", payload.startswith("file:"), repr(payload))
    pfile = os.path.join(gsd.BLOCKS, payload[5:])
    if not os.path.isfile(pfile):
        failures.append("1 engine entry: payload file %s does not exist" % payload)
    else:
        with open(pfile, encoding="utf-8") as fh:
            block = fh.read()
        want("1 payload: starts with the anchor line then the block", block.startswith(ANCHOR + "\n"), repr(block[:40]))
        # the state the other GSD commands read back must be named, or the block could drop it unnoticed
        for needle in ("MANIFEST.md", "README.md", "verdict", "commit", "subagent", "never", "main agent"):
            want("1 payload: names %r" % needle, needle in block)
        for step in STEPS:
            want("1 payload: names the step `%s` it overrides" % step, "`%s`" % step in block)

# 2. a small fixture: the block lands before the rest, a second application changes nothing, a rewritten first line errors
FIXTURE = "<purpose>\nrest of the purpose\n</purpose>\n\n<process>\nbody\n</process>\n"
if eng is not None and block is not None:
    once, errs = patched(FIXTURE, "workflows/spike.md", eng)
    want("2 fixture: no error", not errs, repr(errs))
    want("2 fixture: the block is first", once.startswith(block), repr(once[:60]))
    want("2 fixture: the rest of the file follows it unchanged", once.endswith(FIXTURE[len(ANCHOR):]), repr(once[-60:]))
    twice, errs = patched(once, "workflows/spike.md", eng)
    want("2 fixture: a second application changes nothing", twice == once and not errs, repr(errs))
    moved, errs = patched("<intro>\nrewritten upstream\n", "workflows/spike.md", eng)
    want("2 fixture: a rewritten first line is an error, not a silent skip", len(errs) == 1 and moved == "<intro>\nrewritten upstream\n", repr(errs))
else:
    failures.append("2 fixture: no engine entry with a payload file to apply (see case 1)")

# 3. the real staged workflow, read only
real = read_real("gsd-core/workflows/spike.md")
if real is None:
    print("NOT RUN, NOT ARMED: 3 staged spike.md -- %s has no gsd-core/workflows/spike.md" % STAGE)
elif eng is None or block is None:
    failures.append("3 staged spike.md: no engine entry with a payload file to apply (see case 1)")
else:
    once, errs = patched(real, "workflows/spike.md", eng)
    want("3 staged spike.md: the anchor still matches upstream", not errs, repr(errs))
    want("3 staged spike.md: the block comes first and the upstream file follows it whole",
         once.startswith(block) and once.endswith(real[len(ANCHOR):]), repr(once[:60]))
    twice, errs = patched(once, "workflows/spike.md", eng)
    want("3 staged spike.md: a second application changes nothing", twice == once and not errs, repr(errs))
    # an instruction that names a step upstream has renamed is a dead instruction
    upstream = set(re.findall(r'<step name="([a-z_]+)">', real))
    want("3 staged spike.md: every step the block overrides exists upstream", not (set(STEPS) - upstream),
         "missing %s" % sorted(set(STEPS) - upstream))

# 4. the skill entry
sk = gsd.SKILL_PATCHES.get("gsd-spike")
OLD = ("Preserve all workflow gates (prior spike check, decomposition, research, risk ordering, observability "
       "assessment, verification, MANIFEST updates, commit patterns).")
if sk is None:
    failures.append("4 skill entry: gsd-spike is not a key of SKILL_PATCHES (keys %s)" % sorted(gsd.SKILL_PATCHES))
else:
    want("4 skill entry: one replace patch whose anchor is the sentence", len(sk) == 1 and sk[0][1] == "replace" and sk[0][2] == OLD, repr(sk))
    new = sk[0][3]
    want("4 skill entry: the new sentence is not a substring of the old one (it would read as applied)", new not in OLD)
    for needle in ("MANIFEST", "commit", "README", "subagent"):
        want("4 skill entry: the new sentence names %r" % needle, needle in new)
    want("4 skill entry: the new sentence drops the gate list", "risk ordering" not in new and "observability" not in new)
    fx = "<process>\nParse.\n\n%s\n</process>\n" % OLD
    out, errs = patched(fx, "gsd-spike", sk)
    want("4 skill fixture: no error and the sentence is gone", not errs and SENTENCE_START not in out, repr(errs))
    want("4 skill fixture: the new sentence is in and the rest is untouched", out == fx.replace(OLD, new), repr(out))
    again, errs = patched(out, "gsd-spike", sk)
    want("4 skill fixture: a second application changes nothing", again == out and not errs, repr(errs))
    skill = read_real("skills/gsd-spike/SKILL.md")
    if skill is None:
        print("NOT RUN, NOT ARMED: 4 staged gsd-spike skill -- %s has no skills/gsd-spike/SKILL.md" % STAGE)
    else:
        out, errs = patched(skill, "gsd-spike", sk)
        want("4 staged skill: the anchor still matches upstream", not errs, repr(errs))
        want("4 staged skill: the sentence is gone from the patched text", SENTENCE_START not in out)
        want("4 staged skill: the text differs from upstream by that sentence only", out == skill.replace(OLD, new))

for f in failures:
    print("FAIL " + f)
print("%d failure(s)" % len(failures))
sandbox.cleanup(bool(failures))
sys.exit(1 if failures else 0)
