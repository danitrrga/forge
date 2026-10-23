from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SITE_TZ = ZoneInfo("Europe/Madrid")
FMT = "%Y-%m-%d %H:%M"


def parse_local(text):
    """A wall-clock time at the site, such as '2026-03-28 22:00', as an aware datetime."""
    return datetime.strptime(text, FMT).replace(tzinfo=SITE_TZ)


def shift_hours(start, end):
    """Hours actually worked between two site wall-clock times."""
    return (parse_local(end) - parse_local(start)).total_seconds() / 3600


def shift_end(start, hours):
    """The site wall-clock time at which a shift that starts at `start` ends after `hours` hours of work."""
    return (parse_local(start) + timedelta(hours=hours)).strftime(FMT)


def week_hours(shifts):
    """Total hours worked over a list of (start, end) pairs."""
    return sum(shift_hours(start, end) for start, end in shifts)
