Don't merge yet: `pay` retries `payments.charge` without an idempotency key. `charge` is documented as non-idempotent without one, so a timeout that actually succeeded leads to a double charge. Add `key=order["id"]`. Review is in REVIEW.md.

VERDICT: request changes
