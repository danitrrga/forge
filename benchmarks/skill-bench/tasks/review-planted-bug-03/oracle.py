"""Oracle for review-planted-bug-03.

The diff changes an equality check into a membership test against a constant defined outside the diff.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
the defect is named by `ADMIN_ROLES` and the reason (a string, so `in` is a substring test). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "8d636fc5b34143666299ab6c427e65547c7145074cddc65a581039da5a8a0f03",
    "perms.py": "927d7dd67a257d72bcbdb8f310c90776c1299064bf4f99323b4ac40e43bf91e8",
    "roles.py": "98e63c1727b7ce6a2d79ad21f775dad1ca666002bb936300777e36204d97aa7f"
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
    out.append({"id": "names-the-defect", "passed": bool(re.search('ADMIN_ROLES', text)) and bool(re.search('substring|string|tuple|empty|list|set', text, re.I)),
                "evidence": "the reply names ADMIN_ROLES and says why (a string, so `in` is a substring test)"})
    changed = [f for f, h in SRC.items()
               if not os.path.isfile(os.path.join(repo, f)) or hashlib.sha256(open(os.path.join(repo, f), "rb").read()).hexdigest() != h]
    out.append({"id": "code-untouched", "passed": not changed, "evidence": "changed: %s" % (", ".join(changed) or "none")})
    return out
