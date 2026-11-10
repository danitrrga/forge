# copied-from: marshal-factory lib/globs.ts @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python.
"""Path globs: `**` spans directories, `*` and `?` stay inside one, and a leading `**/` also matches the root.

`vercel.json` names the root file only, `*.ts` a `.ts` file of the root, `**/migrations/**` a `migrations` directory at
any depth, root included. A glob must cover the whole path. Everything else, `[`, `{` and `+` among it, is literal.
"""
import re


def glob_to_regex(glob):
    """The compiled pattern of a glob."""
    source = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*" and glob[i + 1:i + 2] == "*":
            if glob[i + 2:i + 3] == "/":
                source.append("(?:.*/)?")
                i += 3
            else:
                source.append(".*")
                i += 2
        elif c == "*":
            source.append("[^/]*")
            i += 1
        elif c == "?":
            source.append("[^/]")
            i += 1
        else:
            source.append(re.escape(c))
            i += 1
    return re.compile("".join(source) + r"\Z", re.DOTALL)


def matches(path, glob):
    """True when the glob covers the whole path."""
    return glob_to_regex(glob).match(path) is not None


def matches_any(path, globs):
    """True when any of the globs covers the path; False for no globs."""
    return any(matches(path, g) for g in globs)
