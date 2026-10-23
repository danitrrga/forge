"""Fetch exchange rates every minute and save them for the dashboard: python3 refresher.py"""
import random
import time

from rates.store import save_rates

RATES_FILE = "rates.json"


def fetch_rates():
    """Stand-in for the rate provider's API."""
    return {
        "USD": round(1.08 + random.uniform(-0.01, 0.01), 4),
        "GBP": round(0.85 + random.uniform(-0.01, 0.01), 4),
        "JPY": round(162.0 + random.uniform(-1, 1), 2),
    }


def main():
    while True:
        save_rates(RATES_FILE, fetch_rates())
        time.sleep(60)


if __name__ == "__main__":
    main()
