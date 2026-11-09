# copied-from: marshal-factory lib/factory.ts:7-37 @999ad209598517a4c826073b5a0edc2a4097a4fa, ported to Python and
# with the attempt branch `factory-<key>` in place of marshal's `factory/<key>`.
"""Job keys and attempt branches.

A job key names a job in every source and is its branch name: `<PREFIX>-<n>` or `<PREFIX>-<scope>-<n>`. PREFIX names the
source's namespace (a Linear team key such as DTC; GH for GitHub issues), scope is an optional lowercase slug (a repo
name) and n the source's number. A key always ends in digits, so the attempt suffix `-a<n>` never reads as part of one.

The attempt branch of a key is `factory-<key>` for the first attempt and `factory-<key>-a<n>` from the second:
`factory-DTC-12`, `factory-DTC-12-a2`. The slash form marshal used (`factory/DTC-12`) is not a branch here. A key stays within MAX_KEY_LENGTH characters.
"""
import re

BRANCH_PREFIX = "factory-"
MAX_KEY_LENGTH = 64

_KEY = r"[A-Za-z][A-Za-z0-9]*(?:-[a-z0-9]+)*-[0-9]+"
_KEY_PATTERN = re.compile(r"(?:%s)\Z" % _KEY)
_BRANCH_PATTERN = re.compile(r"%s(%s)(?:-a([0-9]+))?\Z" % (re.escape(BRANCH_PREFIX), _KEY))
_PREFIX_PATTERN = re.compile(r"[A-Z][A-Z0-9]*\Z")


def is_job_key(value):
    """True for a well-formed key of at most MAX_KEY_LENGTH characters."""
    return isinstance(value, str) and len(value) <= MAX_KEY_LENGTH and _KEY_PATTERN.match(value) is not None


def _slug(value):
    """Lowercase letters and digits between single hyphens, as a key's scope takes them."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def job_key(prefix, number, scope=None):
    """The key for a source's item: job_key("DTC", 12) is DTC-12, job_key("GH", 42, "acme/Web App") GH-acme-web-app-42."""
    parts = [prefix] + ([_slug(scope)] if scope else []) + [str(number)]
    key = "-".join(p for p in parts if p)
    if not _PREFIX_PATTERN.match(str(prefix)) or not is_job_key(key):
        raise ValueError("cannot make a job key from %s, %s, %s" % (prefix, scope if scope else "no scope", number))
    return key


def attempt_branch(key, attempt):
    """factory-DTC-12 is the first attempt at DTC-12; factory-DTC-12-a2 the second."""
    return "%s%s-a%d" % (BRANCH_PREFIX, key, attempt) if attempt > 1 else BRANCH_PREFIX + key


def parse_branch(branch):
    """{"key", "attempt"} for an attempt branch; None for any other branch, or for a key over MAX_KEY_LENGTH."""
    if not isinstance(branch, str):
        return None
    m = _BRANCH_PATTERN.match(branch)
    if not m or len(m.group(1)) > MAX_KEY_LENGTH:
        return None
    return {"key": m.group(1), "attempt": int(m.group(2)) if m.group(2) else 1}
