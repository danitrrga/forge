The diff only shows the retry loop; the risk is in `charge` (payments.py): no key means every call is a new charge. Duplicate payments on timeout.

VERDICT: request changes
