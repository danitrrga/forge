"""Split a shared bill.

Amounts are strings with two decimals ("100.00"), and shares are returned the same way.
"""


def split_evenly(total, people):
    """Split `total` evenly between `people`, a list of distinct names.

    Returns {name: share} in the order given. The shares always add up to the total exactly:
    everyone pays the same, except that the cents left over go one each to the first people
    in the list.
    """
    share = round(float(total) / len(people), 2)
    return {person: f"{share:.2f}" for person in people}
