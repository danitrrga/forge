"""Oracle for review-planted-bug-02.

The diff wraps a payment call in a retry loop; whether the call is safe to repeat is defined outside the diff.

The reply and REVIEW.md are read for a `VERDICT:` line (REVIEW.md wins when both have one). Facts are matched, not phrasings:
the defect is named by `charge` and the reason (idempotency or a double charge). The code and change.diff must be left as they were: a review that edits the code under review is not a review."""
import hashlib
import os
import re

SRC = {
    "change.diff": "a709d70ec1c061213d4bc05911e506ebcb9cc013506e132cb4442a85d4113d00",
    "checkout.py": "9e31ad4a5f822e73e801dc46c2a805c17f828313c26da4e335eccbfe020e318e",
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
    out = [{"id": "verdict", "passed": got == 'request changes', "evidence": "verdict %r, want %r" % (got, 'request changes')}]
    out.append({"id": "names-the-defect", "passed": bool(re.search('charge', text)) and bool(re.search('idempoten|twice|double|duplicate', text, re.I)),
                "evidence": "the reply names charge and says why (idempotency or a double charge)"})
    changed = [f for f, h in SRC.items()
               if not os.path.isfile(os.path.join(repo, f)) or hashlib.sha256(open(os.path.join(repo, f), "rb").read()).hexdigest() != h]
    out.append({"id": "code-untouched", "passed": not changed, "evidence": "changed: %s" % (", ".join(changed) or "none")})
    return out
