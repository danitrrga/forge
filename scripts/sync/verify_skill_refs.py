#!/usr/bin/env python3
"""Fail if any profile's skills_keep names a skill that is not installed, or keeps nothing.

Set subtraction in forge/skills.py write_settings_local makes a dangling entry a silent no-op, so a
renamed or deleted skill would otherwise sit in the profiles forever while the
SessionStart banner kept counting it in "kept-global N". Exit 0 = every name resolves.

An EMPTY skills_keep fails too. `[]` is not "keep nothing on purpose", it
is trimming switched on with nothing behind it: every global skill off, no message anywhere.
One project was created that way by the new-project skill and ran its whole life with all 25
GSD skills and the entire COMMON layer dark, the only symptom being a command that did
nothing. A profile that really wants no trimming drops the key instead.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from forge import lib, skills  # noqa: E402


def main():
    # The generator's own definition of an installed skill: a dot directory (~/.claude/skills/.trash)
    # is not one, so `skills_keep: [".trash"]` passed here while the generator never kept it.
    installed = skills.global_skills()
    bad = 0
    # A profile lib cannot read is skipped by lib.profiles(); it is counted here, so a broken
    # profile still exits 1 as the json.load traceback did, now on its own line.
    skipped = []
    for name, prof in lib.profiles(skipped).items():
        keep = prof.get("skills_keep")
        if keep is None:
            print("  - %-28s no skills_keep (untrimmed pass-through)" % name)
            continue
        if keep == []:
            bad += 1
            print("  ! %-28s skills_keep: [] -- trimming ON, every global skill off" % name)
            continue
        if "*" in keep:
            # Keep-all wildcard (forge): not a skill name, so it can never dangle.
            print("  = %-28s keep-all wildcard (*), %d installed skills available"
                  % (name, len(installed)))
            continue
        missing = [s for s in keep if s not in installed]
        if missing:
            bad += len(missing)
            print("  ! %-28s %d dangling: %s" % (name, len(missing), ", ".join(missing)))
        else:
            print("  = %-28s %3d names, all resolve" % (name, len(keep)))
    for fname, why in skipped:
        bad += 1
        print("  ! %-28s could not be read: %s" % (fname, why))
    print("\n%d installed skills | %s" % (len(installed),
          "%d problem(s)" % bad if bad else "every skills_keep name resolves, none empty"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
