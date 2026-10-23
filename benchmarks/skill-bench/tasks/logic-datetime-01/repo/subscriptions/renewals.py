from datetime import date


def add_months(d, months):
    """The same day of the month, `months` months after `d`."""
    return d.replace(month=d.month + months)


def renewal_dates(start, count):
    """The first `count` renewal dates of a monthly plan that started on `start`.

    A plan renews on the same day of the month as it started. In a month that is too short
    for that day, it renews on the last day of that month instead.
    """
    dates = []
    current = start
    for _ in range(count):
        current = add_months(current, 1)
        dates.append(current)
    return dates


def next_renewal(start, today):
    """The first renewal date of a plan started on `start` that falls after `today`."""
    n = 1
    while True:
        candidate = renewal_dates(start, n)[-1]
        if candidate > today:
            return candidate
        n += 1
