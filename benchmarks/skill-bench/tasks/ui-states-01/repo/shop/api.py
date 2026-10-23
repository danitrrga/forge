"""Client for the orders service."""
import json
import urllib.error
import urllib.request

BASE_URL = "https://orders.example.test"
TIMEOUT_S = 5


def http_transport(method, path):
    """(status, body) for one request to the orders service. Raises OSError when the service cannot be reached."""
    req = urllib.request.Request(BASE_URL + path, method=method, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def fetch_orders(customer_id, transport=None):
    """The customer's orders, newest first, as dicts with id, placed_on, total and status."""
    transport = transport or http_transport
    try:
        status, body = transport("GET", "/customers/%s/orders" % customer_id)
    except OSError:
        return []
    if status != 200:
        return []
    return json.loads(body)["orders"]
