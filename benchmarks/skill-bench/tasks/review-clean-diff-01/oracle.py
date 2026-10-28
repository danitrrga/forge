"""Oracle for review-clean-diff-01.

The diff passes a converted weight to a rate lookup whose unit is defined outside the diff, and the conversion matches it.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
none beyond the verdict (the change is correct, so no defect may be required of the reviewer). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "c184e9497ede8d8fb6b14a00cdd7f4531647f833891567bd0ae0c91a2e32cb8d",
    "orders.py": "093ffc06ae2b1bd80176137b04dd095d63557438d1bb66ee7ffcdfbb47dc8db7",
    "rates.py": "8c58b327ab2770716a1cdd238ca415591961da8541774526acdc4b429b96db2f"
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
    out = [{"id": "verdict", "passed": got == 'approve', "evidence": "verdict %r, want %r" % (got, 'approve')}]

    changed = [f for f, h in SRC.items()
               if not os.path.isfile(os.path.join(repo, f)) or hashlib.sha256(open(os.path.join(repo, f), "rb").read()).hexdigest() != h]
    out.append({"id": "code-untouched", "passed": not changed, "evidence": "changed: %s" % (", ".join(changed) or "none")})
    return out
