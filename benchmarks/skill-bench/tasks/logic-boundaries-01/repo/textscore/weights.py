from itertools import combinations
import math


def heaviest_substring(text, weights):
    """
    Find the continuous substring of text which has the maximum total weight, given a dictionary
    where the keys are characters and the values are their weights.

    Parameters:
    - text (str): The input string.
    - weights (dict): The dictionary of character weights. Characters not in it weigh 0.

    Returns:
    - str: The continuous substring with the highest weight.

    Example:
    >>> heaviest_substring('abc', {'a': 10, 'b': -5, 'c': 3})
    'a'
    """
    max_weight = -math.inf
    max_substr = ''
    for start, end in combinations(range(len(text)), 2):
        substr = text[start:end]
        weight = sum(weights.get(c, 0) for c in substr)
        if weight > max_weight:
            max_weight = weight
            max_substr = substr
    return max_substr


def total_weight(text, weights):
    """The total weight of text."""
    return sum(weights.get(c, 0) for c in text)
