"""Oracle for review-clean-diff-02.

The diff wraps a payment call in a retry loop, and the call carries an idempotency key that the callee honours.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
none beyond the verdict (the change is correct, so no defect may be required of the reviewer). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "247b683655740044f60ef691650ec7f66cd47592802e34c77fc9d7ab7a4d17ff",
    "checkout.py": "f47f61aa5f2e024a14a273f655a880e7de28b155fc2f739c03ef4d81aad35ba0",
    "payments.py": "8e3b5795f7ad13951ca7dd62c6e62f70120cc685fb56a3de663a5bd89a6d4ff8"
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
