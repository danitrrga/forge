"""What forge/uninstall.py and scripts/sync/sync_system_doc.py both need to know about the project copy of
AGENT-SYSTEM.md and the pointer block in CLAUDE.md: the banner that heads the copy, the canonical doc, the
markers around the block, and the rule for a file whose markers are not one complete pair. A module with no
argv, no lib.context and no sys.path edit, so uninstall imports it instead of running the script."""
import os

from forge import lib

ROOT_FS = lib.ROOT.replace("\\", "/")  # forward-slash form for doc text
CANON = os.path.join(lib.ROOT, "docs", "AGENT-SYSTEM.md")

GEN_BANNER = (
    "<!-- GENERATED — DO NOT EDIT. Synced from "
    + ROOT_FS + "/docs/AGENT-SYSTEM.md by "
    "scripts/sync/sync_system_doc.py. Edit the canonical copy in forge. -->\n\n"
)

BEGIN = "<!-- BEGIN LIFEOS-SYSTEM-POINTER (managed by sync_system_doc.py) -->"
END = "<!-- END LIFEOS-SYSTEM-POINTER -->"


def marker_error(text):
    """Why the markers in `text` are not forge's one complete pair, or None when they are (or there are none).
    The block is replaced from the first BEGIN to the first END, so a BEGIN quoted in prose or left orphaned
    started the replacement and the user's text up to the END went with it (found in an attack round: the
    second sync took a note away). The same rule ds_readiness applies to its stanza: a file whose markers are
    not one complete pair is refused and named, never guessed at."""
    nb, ne = text.count(BEGIN), text.count(END)
    if nb != ne:
        return "%d BEGIN and %d END marker(s), not one complete pair" % (nb, ne)
    if nb > 1:
        return "%d BEGIN...END pairs, forge writes one" % nb
    if nb and text.index(END) < text.index(BEGIN):
        return "the END marker comes before its BEGIN"
    return None
