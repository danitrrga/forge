import json
from urllib import request

from config import PAYMENTS_URL


def refund(charge_id, amount_cents=None):
    """Refund a captured charge, in full unless amount_cents is given."""
    payload = {"charge": charge_id}
    if amount_cents is not None:
        payload["amount"] = amount_cents
    req = request.Request(PAYMENTS_URL + "/refunds", data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=5) as resp:
        return json.load(resp)
