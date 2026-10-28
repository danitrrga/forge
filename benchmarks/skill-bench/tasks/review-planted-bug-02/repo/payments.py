"""Payment gateway client."""
import uuid


class Timeout(Exception):
    pass


_CHARGES = {}   # idempotency key -> receipt id; a stand-in for the gateway


def charge(account, cents, key=None):
    """Charge `cents` to `account` and return a receipt id.

    NOT idempotent unless `key` is given: without one every call is a new charge, and a call that timed out may still
    have gone through. With the same `key` the gateway returns the first receipt instead of charging again.
    """
    if key is not None and key in _CHARGES:
        return _CHARGES[key]
    receipt = uuid.uuid4().hex
    if key is not None:
        _CHARGES[key] = receipt
    return receipt
