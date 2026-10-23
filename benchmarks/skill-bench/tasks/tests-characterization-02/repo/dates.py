import datetime


def parse_date(s):
    # parse whatever people type in the booking form's date box
    # returns a datetime.date, or None if we can't make sense of it
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    if "-" in s:
        parts = s.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            try:
                y = int(parts[0])
                m = int(parts[1])
                d = int(parts[2])
            except ValueError:
                return None
        else:
            return None
    else:
        sep = None
        for c in "/.":
            if c in s:
                sep = c
                break
        if sep == None:
            return None
        parts = s.split(sep)
        if len(parts) != 3:
            return None
        try:
            d = int(parts[0])
            m = int(parts[1])
            y = int(parts[2])
        except ValueError:
            return None
        if len(parts[2]) == 2:
            if y >= 50:
                y = y + 1900
            else:
                y = y + 2000
        else:
            if len(parts[2]) != 4:
                return None
        if m > 12:
            if d <= 12:
                # somebody typed it the American way round
                t = d
                d = m
                m = t
    try:
        return datetime.date(y, m, d)
    except ValueError:
        return None
