"""Time ranges for the room-booking calendar, as (start, end) minutes since midnight."""


def merge(ranges):
    """Merge overlapping or touching ranges into a sorted list of disjoint ranges.

    >>> merge([(540, 600), (570, 630), (700, 720)])
    [(540, 630), (700, 720)]
    """
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def busy_minutes(ranges):
    """How many minutes of the day the room is booked."""
    return sum(end - start for start, end in merge(ranges))


def free_slots(busy, day_start=480, day_end=1080):
    """The gaps between bookings inside the working day (bookings lie inside the day)."""
    free = []
    cursor = day_start
    for start, end in merge(busy):
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < day_end:
        free.append((cursor, day_end))
    return free
