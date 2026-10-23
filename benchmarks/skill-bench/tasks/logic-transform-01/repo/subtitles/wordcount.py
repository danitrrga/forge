"""Count how many times each word occurs in a subtitle.

The subtitles use only ASCII characters. Characters often speak in casual English, using
contractions like they're or it's; a contraction counts as a single word.

Words can be separated by any form of punctuation (e.g. ":", "!", or "?") or whitespace
(e.g. "\\t", "\\n", or " "). The only punctuation that does not separate words is the apostrophe
in contractions. Numbers are words: in "It costs 100 dollars." 100 is its own word.
Words are case insensitive: "you" occurs three times in "You come back, you hear me? DO YOU HEAR ME?"

Example: "That's the password: 'PASSWORD 123'!", cried the Special Agent.\\nSo I fled.
gives 123: 1, agent: 1, cried: 1, fled: 1, i: 1, password: 2, so: 1, special: 1, that's: 1, the: 2.
"""
import re
from collections import Counter


def count_words(sentence):
    """{word: count} for the subtitle line `sentence`, words lower-cased."""
    return dict(Counter(re.findall(r"[a-z0-9']+", sentence.lower())))


def top_words(sentence, n=10):
    """The n most frequent words, most frequent first; ties keep the order of first appearance."""
    return [word for word, _ in Counter(count_words(sentence)).most_common(n)]
