"""Oracle for review-clean-diff-03.

The diff changes an equality check into a membership test against a tuple defined outside the diff.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
none beyond the verdict (the change is correct, so no defect may be required of the reviewer). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "8d636fc5b34143666299ab6c427e65547c7145074cddc65a581039da5a8a0f03",
    "perms.py": "927d7dd67a257d72bcbdb8f310c90776c1299064bf4f99323b4ac40e43bf91e8",
    "roles.py": "15832ca10014f671e2c6c2f37bbf5272e88c675879801a82d800c58d366e9174"
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
