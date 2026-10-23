import json
from urllib import request

from config import PAYMENTS_URL


def charge(amount_cents, card_token):
    """Authorise a card payment; returns the provider's charge record."""
    body = json.dumps({"amount": amount_cents, "currency": "EUR", "source": card_token}).encode()
    req = request.Request(PAYMENTS_URL + "/charges", data=body, method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=5) as resp:
        return json.load(resp)
