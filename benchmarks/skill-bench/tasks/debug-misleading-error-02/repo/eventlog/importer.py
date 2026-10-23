from eventlog.parser import ParseError, parse_line


def import_file(path):
    """(events, errors): every valid event in the file, and one message per bad line."""
    events, errors = [], []
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            if not line.strip() or line.startswith("#"):
                continue
            try:
                events.append(parse_line(line))
            except ParseError as e:
                errors.append("line %d: %s" % (number, e))
    return events, errors
