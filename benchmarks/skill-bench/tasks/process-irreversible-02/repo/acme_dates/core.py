import re
import warnings
from datetime import date


def parse(text):
    """Strict ISO date: 'YYYY-MM-DD' -> date. Raises ValueError on anything else."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    if not m:
        raise ValueError("not an ISO date: %r" % text)
    return date(*map(int, m.groups()))


def parse_loose(text):
    """Deprecated since 1.9.0, removed in 2.0: accepts 'D/M/YYYY' and 'YYYY.MM.DD' as well. Use parse()."""
    warnings.warn("parse_loose is deprecated and will be removed in 2.0; use parse", DeprecationWarning, stacklevel=2)
    text = text.strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        d, mo, y = map(int, m.groups())
        return date(y, mo, d)
    m = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", text)
    if m:
        return date(*map(int, m.groups()))
    return parse(text)


def format_iso(d):
    return d.isoformat()
