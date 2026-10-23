"""The exchange-rate cache shared by the refresher and the dashboard: one JSON file on disk."""
import json
import time


def save_rates(path, rates):
    """Write the latest rates. The refresher calls this every minute."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"updated": time.time(), "rates": rates}, fh, indent=2, sort_keys=True)


def load_rates(path):
    """The rates last saved, as {currency: rate against EUR}."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["rates"]
