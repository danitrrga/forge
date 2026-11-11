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

BEGIN = "<!-- BEGIN FORGE-SYSTEM-POINTER (managed by sync_system_doc.py) -->"
END = "<!-- END FORGE-SYSTEM-POINTER -->"
# The pair forge wrote before the rename. Still read, never written: a file that carries it is migrated to
# BEGIN/END on the next sync, and uninstall strips it.
OLD_BEGIN = "<!-- BEGIN LIFEOS-SYSTEM-POINTER (managed by sync_system_doc.py) -->"
OLD_END = "<!-- END LIFEOS-SYSTEM-POINTER -->"


def _count(text):
    return text.count(BEGIN), text.count(END), text.count(OLD_BEGIN), text.count(OLD_END)


def block_span(text):
    """(start, end, begin_marker, end_marker) of forge's block in `text`, new pair or old pair, or None when
    `text` holds no complete pair. Callers check marker_error first; this takes the first BEGIN and the first
    END of the pair that is present."""
    for b_mark, e_mark in ((BEGIN, END), (OLD_BEGIN, OLD_END)):
        if b_mark in text and e_mark in text:
            return text.index(b_mark), text.index(e_mark) + len(e_mark), b_mark, e_mark
    return None


def has_marker(text):
    """True when `text` holds any forge marker, new or old."""
    return any(c for c in _count(text))


def marker_error(text):
    """Why the markers in `text` are not forge's one complete pair, or None when they are (or there are none).
    The block is replaced from the first BEGIN to the first END, so a BEGIN quoted in prose or left orphaned
    started the replacement and the user's text up to the END went with it (found in an attack round: the
    second sync took a note away). The same rule ds_readiness applies to its stanza: a file whose markers are
    not one complete pair is refused and named, never guessed at. The old pair counts as forge's too, but one
    old and one new marker in the same file is an error: the sync would otherwise leave two blocks."""
    nb, ne, ob, oe = _count(text)
    if (nb or ne) and (ob or oe):
        return "markers of both the old and the new pointer block, forge writes one"
    if ob or oe:
        nb, ne = ob, oe
        b_mark, e_mark = OLD_BEGIN, OLD_END
    else:
        b_mark, e_mark = BEGIN, END
    if nb != ne:
        return "%d BEGIN and %d END marker(s), not one complete pair" % (nb, ne)
    if nb > 1:
        return "%d BEGIN...END pairs, forge writes one" % nb
    if nb and text.index(e_mark) < text.index(b_mark):
        return "the END marker comes before its BEGIN"
    return None
