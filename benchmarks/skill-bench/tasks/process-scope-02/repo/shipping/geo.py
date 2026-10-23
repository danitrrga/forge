import json
from urllib import parse, request

from config import GEO_URL


def geocode(address):
    """(lat, lon) of a delivery address, for the courier's route."""
    url = GEO_URL + "/search?" + parse.urlencode({"q": address, "limit": 1})
    with request.urlopen(url, timeout=5) as resp:
        hit = json.load(resp)[0]
    return hit["lat"], hit["lon"]
