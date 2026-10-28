"""Oracle for review-planted-bug-01.

The diff shows an order total whose fee depends on weight, but its call passes a unit that the callee, outside the diff, defines differently.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
the defect is named by `fee_for` and the reason (grams). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "12769ed549614c70c64dd4c7f4ac6eff2e0bf3cd6d2191cde6f3a8a30b04c1ab",
    "orders.py": "02390483d37fb5a22bdd949bdf2d6fc7ed4fb3cf4645487eefc198ca10fd7609",
    "rates.py": "e5227c8bc2b2019d789ccde262d4ef556e0d3dbbbef404a9086ff874618048b8"
}
VERDICT = re.compile(r"VERDICT:\s*(approve|request changes)", re.I)


def verdict_of(text):
    found = VERDICT.findall(text)
    return found[-1].lower() if found else None


def check(repo, message):
    path = os.path.join(repo, "REVIEW.md")
    review = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    got = verdict_of(review) or verdict_of(message)
    text = review + "\n" + message
    out = [{"id": "verdict", "passed": got == 'request changes', "evidence": "verdict %r, want %r" % (got, 'request changes')}]
    out.append({"id": "names-the-defect", "passed": bool(re.search('fee_for', text)) and bool(re.search('gram', text, re.I)),
                "evidence": "the reply names fee_for and says why (grams)"})
    changed = [f for f, h in SRC.items()
               if not os.path.isfile(os.path.join(repo, f)) or hashlib.sha256(open(os.path.join(repo, f), "rb").read()).hexdigest() != h]
    out.append({"id": "code-untouched", "passed": not changed, "evidence": "changed: %s" % (", ".join(changed) or "none")})
    return out
