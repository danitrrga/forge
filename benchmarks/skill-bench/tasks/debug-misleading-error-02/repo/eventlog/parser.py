"""Parse lines of the team calendar export: `<start> | <title> | <duration>`.

start is `YYYY-MM-DD HH:MM`; duration is hours and/or minutes: `45m`, `2h`, `1h30m`.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta


class ParseError(ValueError):
    """A line that is not a valid event. The importer reports it with its line number and goes on."""


@dataclass
class Event:
    start: datetime
    title: str
    duration: timedelta


_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?")


def parse_duration(text):
    m = _DURATION.fullmatch(text)
    return timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))


def parse_line(line):
    try:
        start_text, title, duration_text = (part.strip() for part in line.split("|"))
        start = datetime.strptime(start_text, "%Y-%m-%d %H:%M")
        return Event(start, title, parse_duration(duration_text))
    except Exception:
        raise ParseError("invalid date format: %r" % line.split("|")[0].strip())
