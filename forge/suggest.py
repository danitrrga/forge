"""The sentence for a name that does not exist: what was asked, the closest name there is, and every name there is."""
import difflib


def closest(name, options):
    """The option nearest to `name`, or None when none is near enough to be a typo of it."""
    found = difflib.get_close_matches(name, sorted(options), n=1, cutoff=0.6)
    return found[0] if found else None


def message(kind, name, options, where=""):
    """`no profile '@marketng' in project 'app'; did you mean '@marketing'? There are: @code, @marketing`.
    `where` is the owner of the names (' in project ...'), left out when empty."""
    near = closest(name, options)
    return "no %s '%s'%s%s There are: %s" % (
        kind, name, where, "; did you mean '%s'?" % near if near else ".", ", ".join(sorted(options)) or "none")
