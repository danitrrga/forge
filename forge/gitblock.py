"""The block forge keeps in a project's ignore file (.gitignore, or .git/info/exclude for a project whose
.gitignore the repo owns), as text: markers, where it is, whether its markers are one complete pair. No file is
read or written here (forge/fwxignore.py does that), so forge/owned.py can read a block claim without importing
the step.

The block is the framework's (forge/fwxignore.py says why each line is there):

    # BEGIN FORGE-FWX (managed by forge)
    !/.fwx/**/*.md
    /.claude/<plugin>.json
    /.claude/worktrees/
    # END FORGE-FWX

The markers are `#` comments, which a .gitignore reads as comments, so forge/system_doc.py's HTML-comment pair cannot be
reused; its rule is the same, though: markers that are not one complete pair are refused and named, never guessed
at. A line counts as a marker when its stripped text is the marker; one that starts like a marker and is not
exactly it is an edited marker, an error too. Lines are handled with their line endings, so a CRLF file keeps them
outside the block."""

NAME = "FORGE-FWX"
BEGIN = "# BEGIN FORGE-FWX (managed by forge)"
END = "# END FORGE-FWX"
_BEGIN_HEAD, _END_HEAD = "# BEGIN " + NAME, "# END " + NAME


def lines_for(plugin, prefix=""):
    """The block's lines. `prefix` is where the project sits in its repository ("" or "sub/dir/"), for a block in
    .git/info/exclude, whose patterns are anchored at the repository's root."""
    p = "/" + prefix
    return [BEGIN, "!%s.fwx/**/*.md" % p, "%s.claude/%s.json" % (p, plugin), "%s.claude/worktrees/" % p, END]


def text_of(lines):
    """The value a claim holds: the lines joined by newlines, no trailing one."""
    return "\n".join(lines)


def _split(text):
    return text.splitlines(keepends=True)


def _marks(lines):
    begins = [i for i, l in enumerate(lines) if l.strip() == BEGIN]
    ends = [i for i, l in enumerate(lines) if l.strip() == END]
    edited = [i for i, l in enumerate(lines)
              if l.strip() not in (BEGIN, END) and l.strip().startswith((_BEGIN_HEAD, _END_HEAD))]
    return begins, ends, edited


def marker_error(text):
    """(line number, why) for the first fault in the markers of `text`, or None when there is none or one complete
    pair: an edited marker, a BEGIN without an END or the other way round, two blocks, an END before its BEGIN.
    Line numbers count from 1, so they are what `file:line` names."""
    begins, ends, edited = _marks(_split(text))
    if edited:
        return edited[0] + 1, "a marker line was edited (it must read exactly `%s` or `%s`)" % (BEGIN, END)
    if len(begins) != len(ends):
        extra = begins[len(ends)] if len(begins) > len(ends) else ends[len(begins)]
        return extra + 1, "%d BEGIN and %d END marker(s), not one complete pair" % (len(begins), len(ends))
    if len(begins) > 1:
        return begins[1] + 1, "%d BEGIN...END pairs, forge writes one" % len(begins)
    if begins and ends[0] < begins[0]:
        return ends[0] + 1, "the END marker comes before its BEGIN (line %d)" % (begins[0] + 1)
    return None


def span(text):
    """(first line index, last line index), both inclusive and from 0, of the block in `text`, or None when it holds
    none. The caller has checked marker_error."""
    begins, ends, _ = _marks(_split(text))
    return (begins[0], ends[0]) if begins and ends else None


def held(text):
    """The block's lines as a claim holds them (text_of), or None when `text` holds none or a broken pair."""
    s = span(text) if marker_error(text) is None else None
    if s is None:
        return None
    return text_of(l.rstrip("\r\n") for l in _split(text)[s[0]:s[1] + 1])


def without(text):
    """`text` minus the block's lines, and nothing else."""
    s = span(text)
    lines = _split(text)
    return text if s is None else "".join(lines[:s[0]] + lines[s[1] + 1:])


def after(text):
    """The lines that follow the block, with their line endings."""
    s = span(text)
    return [] if s is None else _split(text)[s[1] + 1:]


def append(text, lines):
    """`text` with the block's `lines` at its end, a newline added first when the last line lacks one."""
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "".join(l + "\n" for l in lines)


def replace(text, lines):
    """`text` with the block it holds replaced, in place, by `lines`."""
    s = span(text)
    old = _split(text)
    return "".join(old[:s[0]]) + "".join(l + "\n" for l in lines) + "".join(old[s[1] + 1:])
