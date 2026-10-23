def is_rising(readings):
    """True if every reading is larger than the one before it."""
    return all(b > a for a, b in zip(readings, readings[1:]))


def last_drop(readings):
    """Return the largest index of a reading which is not greater than or equal to the reading
    immediately preceding it. If no such reading exists then return -1. The readings will not
    contain duplicate values.

    Examples:
    last_drop([1, 2, 4, 3, 5]) = 3
    last_drop([1, 2, 3]) = -1
    """
    for i in range(len(readings) - 2, 0, -1):
        if readings[i + 1] < readings[i]:
            return i
    return -1
