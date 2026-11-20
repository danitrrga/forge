"""A run's one-use files end with the work: `prune(phase_dir)` removes the run folders of a phase and its subphases.

`fwx wave new` writes a run's briefs, and each `fwx wave` step its result, in `<git-common-dir>/fwx/runs/<run>/`, outside every general
folder and outside git's history. They are read while the part runs and after it (`fwx wave --run R`), and are of no use once the phase is
`closed`; left alone they only pile up (the ownership rule, playbooks/principles.md rule 12: one-use files do not outlive their work).
`fwx stage` calls this when it moves a session folder to `closed`. A run is named `<part folder name>-<sha>-<n>`, so the folders of the phase
are those named after the phase folder or one of its subphase folders and nothing else. A failure to remove one is not a failure to close.

Imports the standard library and `state`.
"""
import os
import re
import shutil
import subprocess

from fwx import state

_TAIL = r"-[0-9a-f]{7,40}-\d+\Z"


def runs_dir(folder):
    r = subprocess.run(["git", "-C", str(folder), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True)
    return os.path.join(r.stdout.strip(), "fwx", "runs") if r.returncode == 0 and r.stdout.strip() else None


def prune(phase_dir):
    """The names of the run folders removed."""
    root = runs_dir(phase_dir)
    if not root or not os.path.isdir(root):
        return []
    names = [os.path.basename(os.path.abspath(str(phase_dir)))] + [p.name for p in state.subphases(phase_dir)]
    mine = [re.compile(re.escape(n) + _TAIL) for n in names]
    gone = []
    for run in sorted(os.listdir(root)):
        if any(m.match(run) for m in mine):
            try:
                shutil.rmtree(os.path.join(root, run))
                gone.append(run)
            except OSError:
                pass
    return gone
