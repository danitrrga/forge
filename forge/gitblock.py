"""The block forge keeps in a project's ignore file (.gitignore, or .git/info/exclude for a project whose
.gitignore the repo owns), as text: markers, where it is, whether its markers are one complete pair. No file is
read or written here (forge/fwxignore.py does that), so forge/owned.py can read a block claim without importing
the step.

The block is the framework's (forge/fwxignore.py says why each line is there):

    # BEGIN FORGE-FWX (managed by forge, do not edit inside)
    !/.fwx/**/*.md
    !/.fwx/**/*.tsv
    /.claude/<plugin>.json
    /.claude/worktrees/
    # END FORGE-FWX

Everything between the markers is forge's: a sync rewrites it, an uninstall removes it, and the BEGIN line says so.

.git/info/exclude is one file for the whole repository, so each project in it keeps its own block, told apart by a
tag, the project's place in the repository ("sub/dir/"; a project at the root, and every block of a .gitignore, has
none): `# BEGIN FORGE-FWX sub/dir/ (managed by forge, do not edit inside)` and `# END FORGE-FWX sub/dir/`. A tag has no
spaces (they are %-quoted). Every function here that takes a `tag` sees only that project's block.

The markers are `#` comments, which a .gitignore reads as comments, so forge/system_doc.py's HTML-comment pair cannot be
reused; its rule is the same, though: markers that are not one complete pair are refused and named, never guessed
at. A line counts as a marker when its stripped text is the marker; one that starts like a marker and is not
exactly one of forge's is an edited marker, an error too (for every tag: whose it was cannot be told). A block is
written with the line ending its file already uses (eol), and handled with its endings, so a CRLF file keeps its lines
outside the block. A directory name with a glob character (`[`, `]`, `*`, `?`, a backslash) is written escaped in the
lines, and a tag is %-quoted."""
import re
import urllib.parse

NAME = "FORGE-FWX"
NOTE = "(managed by forge, do not edit inside)"
_BEGIN_HEAD, _END_HEAD = "# BEGIN " + NAME, "# END " + NAME
_BEGIN_RE = re.compile(r"^# BEGIN %s(?: (\S+))? %s$" % (NAME, re.escape(NOTE)))
_END_RE = re.compile(r"^# END %s(?: (\S+))?$" % NAME)


def _tag(tag):
    return " " + urllib.parse.quote(tag, safe="/") if tag else ""


def begin(tag=""):
    """The BEGIN marker line of the block of `tag`."""
    return "# BEGIN %s%s %s" % (NAME, _tag(tag), NOTE)


def end(tag=""):
    """The END marker line of the block of `tag`."""
    return "# END %s%s" % (NAME, _tag(tag))


BEGIN, END = begin(), end()  # the untagged pair


def _glob_escape(prefix):
    """`prefix` as a literal in a gitignore pattern: a backslash, `[`, `]`, `*` and `?` in a directory name are not
    wildcards there."""
    return "".join("\\" + c if c in "\\[]*?" else c for c in prefix)


def lines_for(plugin, prefix="", tag=""):
    """The block's lines. `prefix` is where the project sits in its repository ("" or "sub/dir/"), for a block in
    .git/info/exclude, whose patterns are anchored at the repository's root; `tag` names the block in a file several
    projects share. The tsv files get a line too: a project's own `*.tsv`, or a `*` allowlist, ignores them."""
    p = "/" + _glob_escape(prefix)
    return [begin(tag), "!%s.fwx/**/*.md" % p, "!%s.fwx/**/*.tsv" % p, "%s.claude/%s.json" % (p, plugin),
            "%s.claude/worktrees/" % p, end(tag)]


def text_of(lines):
    """The value a claim holds: the lines joined by newlines, no trailing one."""
    return "\n".join(lines)


def _split(text):
    return text.splitlines(keepends=True)


def eol(text):
    """The line ending `text` uses: that of its first line break, "\n" when it has none."""
    i = text.find("\n")
    return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def _marks(lines, tag):
    mine_b, mine_e = begin(tag), end(tag)
    begins = [i for i, l in enumerate(lines) if l.strip() == mine_b]
    ends = [i for i, l in enumerate(lines) if l.strip() == mine_e]
    edited = [i for i, l in enumerate(lines)
              if l.strip().startswith((_BEGIN_HEAD, _END_HEAD)) and not _BEGIN_RE.match(l.strip()) and not _END_RE.match(l.strip())]
    return begins, ends, edited


def marker_error(text, tag=""):
    """(line number, why) for the first fault in the markers of `text` as they concern the block of `tag`, or None
    when there is none or one complete pair: an edited marker (any tag's), a BEGIN without an END or the other way
    round, two blocks of the tag, an END before its BEGIN. Another tag's complete block is nobody's fault here. Line
    numbers count from 1, so they are what `file:line` names."""
    begins, ends, edited = _marks(_split(text), tag)
    if edited:
        return edited[0] + 1, "a marker line was edited (it must read exactly `%s` or `%s`)" % (begin(tag), end(tag))
    if len(begins) != len(ends):
        extra = begins[len(ends)] if len(begins) > len(ends) else ends[len(begins)]
        return extra + 1, "%d BEGIN and %d END marker(s), not one complete pair" % (len(begins), len(ends))
    if len(begins) > 1:
        return begins[1] + 1, "%d BEGIN...END pairs, forge writes one" % len(begins)
    if begins and ends[0] < begins[0]:
        return ends[0] + 1, "the END marker comes before its BEGIN (line %d)" % (begins[0] + 1)
    return None


def span(text, tag=""):
    """(first line index, last line index), both inclusive and from 0, of the block of `tag` in `text`, or None when
    it holds none. The caller has checked marker_error."""
    begins, ends, _ = _marks(_split(text), tag)
    return (begins[0], ends[0]) if begins and ends else None


def held(text, tag=""):
    """The block's lines as a claim holds them (text_of), or None when `text` holds none or a broken pair."""
    s = span(text, tag) if marker_error(text, tag) is None else None
    if s is None:
        return None
    return text_of(l.rstrip("\r\n") for l in _split(text)[s[0]:s[1] + 1])


def without(text, tag=""):
    """`text` minus the block's lines, and nothing else."""
    s = span(text, tag)
    lines = _split(text)
    return text if s is None else "".join(lines[:s[0]] + lines[s[1] + 1:])


def after(text, tag=""):
    """The lines that follow the block of `tag`, with their line endings, but not those of the other projects' blocks
    that follow it in a file several share: those are not lines that decide anything."""
    s = span(text, tag)
    out, inside = [], False
    for l in ([] if s is None else _split(text)[s[1] + 1:]):
        t = l.strip()
        if _BEGIN_RE.match(t):
            inside = True
        elif inside:
            inside = not _END_RE.match(t)
        elif not _END_RE.match(t):
            out.append(l)
    return out


def append(text, lines):
    """`text` with the block's `lines` at its end, in the line ending the text uses, a break added first when the last
    line lacks one."""
    nl = eol(text)
    if text and not text.endswith("\n"):
        text += nl
    return text + "".join(l + nl for l in lines)


def replace(text, lines, tag=""):
    """`text` with the block of `tag` it holds replaced, in place, by `lines`."""
    s = span(text, tag)
    old = _split(text)
    nl = eol(text)
    return "".join(old[:s[0]]) + "".join(l + nl for l in lines) + "".join(old[s[1] + 1:])
