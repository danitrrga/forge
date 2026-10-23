"""Charge through the old v1 endpoint."""
import json
from urllib import parse, request

from config import PAYMENTS_V1_URL


def legacy_charge(amount_cents, card_token):
    body = parse.urlencode({"amount": amount_cents, "card": card_token}).encode()
    with request.urlopen(PAYMENTS_V1_URL + "/charge", data=body, timeout=5) as resp:
        return json.load(resp)
