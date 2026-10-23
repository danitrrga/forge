import json
from urllib import request

from config import PAYMENTS_URL


def capture(charge_id):
    """Capture an authorised charge once the order ships."""
    req = request.Request(PAYMENTS_URL + "/charges/%s/capture" % charge_id, data=b"{}", method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=5) as resp:
        return json.load(resp)
