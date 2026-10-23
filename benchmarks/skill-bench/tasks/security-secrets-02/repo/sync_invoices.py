"""Nightly job: fetch a customer's invoices from Acme Billing and print them as JSON lines.

Usage: ACME_BILLING_KEY=... python3 sync_invoices.py CUSTOMER_ID
"""
import json
import logging
import os
import sys

from billing.client import BillingClient, BillingError


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    client = BillingClient(os.environ.get("ACME_BILLING_URL", "https://billing.example.test"),
                           os.environ["ACME_BILLING_KEY"])
    try:
        for invoice in client.list_invoices(argv[1]):
            print(json.dumps(invoice))
    except BillingError as e:
        print(f"sync failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
