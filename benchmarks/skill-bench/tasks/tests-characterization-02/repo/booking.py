"""Booking form handling."""
from dates import parse_date


def validate(form, today):
    """List of error messages for the booking form (empty when it is fine)."""
    errors = []
    arrive = parse_date(form.get("arrive"))
    leave = parse_date(form.get("leave"))
    if arrive is None:
        errors.append("Arrival date not understood")
    if leave is None:
        errors.append("Departure date not understood")
    if arrive and leave:
        if leave <= arrive:
            errors.append("Departure must be after arrival")
        if arrive < today:
            errors.append("Arrival is in the past")
    return errors
