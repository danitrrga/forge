MAX_LINES = 4
MAX_WIDTH = 32


def format_address(lines):
    """Address block for the label: upper case, blank lines dropped, at most 4 lines of 32 characters."""
    clean = [" ".join(l.split()).upper() for l in lines if l and l.strip()]
    if len(clean) > MAX_LINES:
        raise ValueError("address has %d lines, the label fits %d" % (len(clean), MAX_LINES))
    for l in clean:
        if len(l) > MAX_WIDTH:
            raise ValueError("address line too long for the label: %r" % l)
    return clean
