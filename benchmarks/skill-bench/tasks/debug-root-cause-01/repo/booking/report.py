"""Daily utilisation report for one room."""
from booking.intervals import busy_minutes, free_slots


def hhmm(minutes):
    return "%02d:%02d" % divmod(minutes, 60)


def daily_report(bookings, day_start=480, day_end=1080):
    used = busy_minutes(bookings)
    lines = ["booked %d of %d minutes" % (used, day_end - day_start)]
    for start, end in free_slots(bookings, day_start, day_end):
        lines.append("free %s-%s" % (hhmm(start), hhmm(end)))
    return "\n".join(lines)
